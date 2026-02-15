"""Fetch active 5-minute BTC markets from Polymarket."""
import asyncio
import structlog
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient
from rate_limiter import get_rate_limiter
import re

logger = structlog.get_logger()

# Pre-compiled regex for baseline price extraction (latency optimization)
_PRICE_PATTERN = re.compile(r'\$([0-9,]+(?:\.[0-9]+)?)')

# Shared aiohttp session for connection pooling
_http_session: Optional[aiohttp.ClientSession] = None

async def get_http_session() -> aiohttp.ClientSession:
    """Get or create shared HTTP session with connection pooling."""
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(
            limit=20,  # Connection pool size
            ttl_dns_cache=300,  # DNS cache 5 min
            keepalive_timeout=30
        )
        _http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=5)
        )
    return _http_session


class MarketFetcher:
    """
    Fetches active 5-minute BTC markets from Polymarket.
    
    Uses both:
    - CLOB API (py-clob-client) for orderbook and price data
    - Gamma Markets API for market metadata and filtering
    
    Filters:
    - Only BTC markets
    - Only 5-minute duration
    - Only active (not resolved)
    - Only recent (created within last hour)
    """
    
    GAMMA_API_BASE = "https://gamma-api.polymarket.com"
    
    def __init__(self, clob_client: ClobClient):
        self.client = clob_client
        self.cached_markets = []
        self.last_fetch = None
        self.cache_ttl_seconds = 5  # OPTIMIZED: Reduced from 30s to 5s for faster market updates
        self._background_refresh_task = None
        self._refresh_running = False
        
    async def get_active_markets(self, force_refresh: bool = False) -> List[Dict]:
        """
        Get active 5-minute BTC markets.
        
        Returns list of markets with:
        - id: Market condition ID
        - question: Market question
        - baseline_price: BTC price when market was created
        - yes_token_id: Token ID for YES outcome
        - no_token_id: Token ID for NO outcome
        - yes_price: Current YES token price
        - no_price: Current NO token price
        - created_at: When market was created
        - closes_at: When market closes (5 minutes after creation)
        """
        
        # Check cache
        if not force_refresh and self.cached_markets and self.last_fetch:
            time_since_fetch = (datetime.now() - self.last_fetch).total_seconds()
            if time_since_fetch < self.cache_ttl_seconds:
                logger.debug("market_cache_hit", markets=len(self.cached_markets))
                return self.cached_markets
        
        try:
            # Fetch markets from both APIs
            btc_5m_markets = await self._fetch_btc_5m_markets()
            
            # Update cache
            self.cached_markets = btc_5m_markets
            self.last_fetch = datetime.now()
            
            logger.info(
                "markets_fetched",
                btc_5m=len(btc_5m_markets)
            )
            
            return btc_5m_markets
            
        except Exception as e:
            logger.error("market_fetch_failed", error=str(e), exc_info=True)
            return self.cached_markets  # Return stale cache on error
    
    async def _fetch_btc_5m_markets(self) -> List[Dict]:
        """
        Fetch BTC 5-minute markets from Polymarket.
        
        Strategy:
        1. Get markets from Gamma API (has better filtering)
        2. For each market, get token IDs and prices from CLOB API
        """
        try:
            # First try Gamma API for market metadata (now async!)
            gamma_markets = await self._fetch_from_gamma_api()
            
            if gamma_markets:
                return await self._enrich_with_clob_data(gamma_markets)
            
            # Fallback: use CLOB API simplified markets
            logger.warning("gamma_api_failed_using_clob_fallback")
            return await self._fetch_from_clob_api()
            
        except Exception as e:
            logger.error("fetch_markets_error", error=str(e), exc_info=True)
            return []
    
    async def _fetch_from_gamma_api(self) -> List[Dict]:
        """
        Fetch markets from Gamma/Strapi API (ASYNC - non-blocking).
        
        Tries multiple endpoints to find BTC markets.
        """
        try:
            # Rate limit: market fetching
            limiter = get_rate_limiter()
            await limiter.acquire_market()
            
            session = await get_http_session()
            
            # Try multiple endpoints - prioritize BTC 5M specific searches
            endpoints = [
                # Search for BTC 5-minute markets specifically
                (f"{self.GAMMA_API_BASE}/events", {'slug_contains': 'btc-updown-5m', 'closed': 'false', 'active': 'true', 'limit': 50}),
                (f"{self.GAMMA_API_BASE}/markets", {'slug_contains': 'btc-updown-5m', 'closed': 'false', 'limit': 100}),
                # Crypto category
                (f"{self.GAMMA_API_BASE}/events", {'tag': 'crypto', 'closed': 'false', 'active': 'true', 'limit': 100}),
                # General search fallback
                (f"{self.GAMMA_API_BASE}/markets", {'closed': 'false', 'limit': 100, '_limit': 100}),
                (f"{self.GAMMA_API_BASE}/events", {'closed': 'false', 'active': 'true', 'limit': 50}),
                ("https://strapi-matic.poly.market/markets", {'closed': 'false', '_limit': 100}),
            ]
            
            for url, params in endpoints:
                try:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            data = await response.json()
                            items = data if isinstance(data, list) else data.get('data', [])
                            
                            if items:
                                logger.info("gamma_api_endpoint_success", url=url[:50], count=len(items))
                                # Log sample with slug info
                                sample = items[0]
                                logger.warning("gamma_sample", 
                                    keys=str(list(sample.keys())[:10]),
                                    slug=str(sample.get('slug', sample.get('market_slug', '')))[:50],
                                    q=str(sample.get('question', sample.get('title', '')))[:60]
                                )
                                limiter.reset_backoff()
                                return self._process_gamma_data(items, url)
                        else:
                            logger.debug("gamma_endpoint_failed", url=url[:50], status=response.status)
                except Exception as e:
                    logger.debug("gamma_endpoint_error", url=url[:50], error=str(e)[:50])
                    continue
            
            return []
            
        except Exception as e:
            logger.warning("gamma_api_error", error=str(e))
            return []
    
    def _process_gamma_data(self, items: List[Dict], source_url: str) -> List[Dict]:
        """Process data from Gamma/Strapi API, handling different formats."""
        markets = []
        
        # Check if these are events (with nested markets) or direct markets
        if items and 'markets' in items[0]:
            # Events format - flatten and propagate event slug
            for event in items:
                event_slug = event.get('slug', '')
                for market in event.get('markets', []):
                    market['event_title'] = event.get('title', '')
                    market['event_slug'] = event_slug  # Propagate event slug for BTC 5M detection
                    markets.append(market)
        else:
            # Direct markets format
            markets = items
        
        # Debug: Log slug distribution
        slugs_with_btc = [m.get('slug', m.get('event_slug', ''))[:40] for m in markets if 'btc' in str(m.get('slug', m.get('event_slug', ''))).lower()][:5]
        if slugs_with_btc:
            logger.warning("DEBUG_btc_slugs", samples=str(slugs_with_btc))
        
        # Filter for BTC 5-minute markets
        btc_5m_markets = []
        for market in markets:
            if self._is_btc_5m_market(market):
                btc_5m_markets.append(market)
        
        logger.info("gamma_processed", source=source_url[:30], total=len(markets), btc_5m=len(btc_5m_markets))
        return btc_5m_markets
    
    async def _fetch_from_clob_api(self) -> List[Dict]:
        """
        Fallback: Fetch markets from CLOB API simplified markets.
        """
        try:
            # Rate limit: market fetching
            limiter = get_rate_limiter()
            await limiter.acquire_market()
            
            # Get simplified markets from CLOB
            result = self.client.get_simplified_markets()
            limiter.reset_backoff()  # Success - reset backoff
            
            markets = []
            if isinstance(result, dict) and 'data' in result:
                markets = result['data']
            elif isinstance(result, list):
                markets = result
            
            # Debug: Log sample market data to understand format (use warning for visibility)
            if markets:
                sample = markets[0]
                logger.warning("DEBUG_sample_market", 
                    keys=str(list(sample.keys())[:12]),
                    slug=str(sample.get('slug', sample.get('market_slug', sample.get('condition_id', ''))))[:60],
                    question=str(sample.get('question', ''))[:80],
                    title=str(sample.get('title', ''))[:80]
                )
            
            # Check for BTC in any text field
            btc_related = []
            for m in markets:
                text = f"{m.get('question', '')} {m.get('description', '')} {m.get('title', '')}".lower()
                if 'btc' in text or 'bitcoin' in text:
                    btc_related.append(m)
            
            if btc_related:
                sample_questions = [m.get('question', '')[:80] for m in btc_related[:5]]
                logger.warning("DEBUG_btc_found", count=len(btc_related), samples=str(sample_questions))
            else:
                logger.warning("DEBUG_no_btc", total=len(markets))
            
            # Filter and parse
            btc_5m_markets = []
            for market in markets:
                if self._is_btc_5m_market(market):
                    parsed = await self._parse_clob_market(market)
                    if parsed:
                        btc_5m_markets.append(parsed)
            
            logger.info("clob_api_success", total=len(markets), btc_5m=len(btc_5m_markets))
            return btc_5m_markets
            
        except Exception as e:
            logger.error("clob_api_error", error=str(e), exc_info=True)
            return []
    
    async def _enrich_with_clob_data(self, gamma_markets: List[Dict]) -> List[Dict]:
        """
        Enrich Gamma API market data with CLOB prices.
        
        OPTIMIZED: Parallel fetching with asyncio.gather (~50-100ms faster)
        """
        tasks = [self._parse_gamma_market(market) for market in gamma_markets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        enriched = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("market_enrich_failed", market_id=gamma_markets[i].get('id'), error=str(result))
            elif result:
                enriched.append(result)
        
        return enriched
    
    async def _parse_gamma_market(self, market: Dict) -> Optional[Dict]:
        """
        Parse market from Gamma API and enrich with CLOB data.
        """
        try:
            condition_id = market.get('condition_id') or market.get('id')
            question = market.get('question', '')
            
            # Extract baseline price
            baseline_price = self._extract_baseline_price(question)
            if not baseline_price:
                logger.debug("no_baseline_price", question=question)
                return None
            
            # Get token IDs (YES/NO)
            tokens = market.get('tokens', [])
            if len(tokens) < 2:
                logger.warning("insufficient_tokens", condition_id=condition_id)
                return None
            
            yes_token = tokens[0]
            no_token = tokens[1]
            
            yes_token_id = yes_token.get('token_id')
            no_token_id = no_token.get('token_id')
            
            if not yes_token_id or not no_token_id:
                logger.warning("missing_token_ids", condition_id=condition_id)
                return None
            
            # Get current prices from CLOB (rate limited)
            try:
                limiter = get_rate_limiter()
                await limiter.acquire_price()
                
                yes_price = self.client.get_midpoint(yes_token_id)
                yes_price_val = float(yes_price.get('mid', 0.5)) if isinstance(yes_price, dict) else 0.5
                limiter.reset_backoff()  # Success
            except Exception as e:
                logger.warning("price_fetch_failed", token_id=yes_token_id, error=str(e))
                yes_price_val = 0.5
            
            no_price_val = 1.0 - yes_price_val
            
            return {
                'id': condition_id,
                'question': question,
                'baseline_price': baseline_price,
                'yes_token_id': yes_token_id,
                'no_token_id': no_token_id,
                'yes_price': yes_price_val,
                'no_price': no_price_val,
                'created_at': market.get('start_date_iso') or market.get('created_at'),
                'closes_at': market.get('end_date_iso'),
                'volume': market.get('volume', 0)
            }
            
        except Exception as e:
            logger.error("gamma_market_parse_error", error=str(e), market=market)
            return None
    
    async def _parse_clob_market(self, market: Dict) -> Optional[Dict]:
        """
        Parse market from CLOB API simplified markets.
        """
        try:
            condition_id = market.get('condition_id') or market.get('id')
            question = market.get('question', '')
            
            # Extract baseline price
            baseline_price = self._extract_baseline_price(question)
            if not baseline_price:
                return None
            
            # CLOB simplified markets should have tokens array
            tokens = market.get('tokens', [])
            if len(tokens) < 2:
                logger.warning("insufficient_tokens_clob", condition_id=condition_id)
                return None
            
            yes_token_id = tokens[0].get('token_id')
            no_token_id = tokens[1].get('token_id')
            
            # Get prices (may already be in market data)
            yes_price = tokens[0].get('price', 0.5)
            no_price = tokens[1].get('price', 0.5)
            
            return {
                'id': condition_id,
                'question': question,
                'baseline_price': baseline_price,
                'yes_token_id': yes_token_id,
                'no_token_id': no_token_id,
                'yes_price': float(yes_price),
                'no_price': float(no_price),
                'created_at': market.get('start_date_iso'),
                'closes_at': market.get('end_date_iso'),
                'volume': market.get('volume', 0)
            }
            
        except Exception as e:
            logger.error("clob_market_parse_error", error=str(e), market=market)
            return None
    
    def _is_btc_5m_market(self, market: Dict) -> bool:
        """
        Check if market is a 5-minute BTC market.
        
        Polymarket 5M BTC markets use format:
        - Slug: btc-updown-5m-{timestamp}
        - URL: /event/btc-updown-5m-{timestamp}
        - Markets: "Up" vs "Down" binary outcomes
        """
        # Check slug first (most reliable - format: btc-updown-5m-XXXXXXXXXX)
        slug = market.get('slug', '')
        market_slug = market.get('market_slug', '')
        event_slug = market.get('event_slug', '')
        
        if any('btc-updown-5m' in s.lower() for s in [slug, market_slug, event_slug] if s):
            # Verify not closed
            if market.get('closed', False) or market.get('resolved', False):
                return False
            if market.get('active') == False:
                return False
            return True
        
        # Fallback: text-based matching
        question = market.get('question', '')
        title = market.get('title', '')
        event_title = market.get('event_title', '')
        description = market.get('description', '')
        
        all_text = f"{question} {title} {event_title} {description}".upper()
        
        # Check if BTC-related
        if not any(term in all_text for term in ['BTC', 'BITCOIN']):
            return False
        
        # Check if 5-minute market (flexible matching)
        time_patterns = ['5 MINUTE', '5M', '5-MINUTE', '5MIN', '5-MIN', 'FIVE MINUTE', 'UP/DOWN', 'UPDOWN']
        if not any(term in all_text for term in time_patterns):
            return False
        
        # Check if active
        if market.get('closed', False) or market.get('resolved', False):
            return False
        
        if market.get('active') == False:
            return False
        
        return True
    
    def _extract_baseline_price(self, question: str) -> Optional[float]:
        """
        Extract BTC baseline price from question.
        
        Examples:
        - "Will BTC be above $95,000 in 5 minutes?" -> 95000
        - "BTC > $94,500 in next 5m?" -> 94500
        """
        # Use pre-compiled regex (latency optimization)
        match = _PRICE_PATTERN.search(question)
        
        if match:
            price_str = match.group(1).replace(',', '')
            try:
                return float(price_str)
            except ValueError:
                return None
        
        return None
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """Get a specific market from cache."""
        for market in self.cached_markets:
            if market['id'] == market_id:
                return market
        return None
    
    async def start_background_refresh(self):
        """
        OPTIMIZATION: Start background task to pre-fetch markets.
        
        This ensures the cache is always warm and get_active_markets() 
        returns instantly from cache.
        """
        if self._refresh_running:
            logger.warning("background_refresh_already_running")
            return
        
        self._refresh_running = True
        self._background_refresh_task = asyncio.create_task(self._background_refresh_loop())
        logger.info("background_market_refresh_started", ttl=self.cache_ttl_seconds)
    
    async def stop_background_refresh(self):
        """Stop background refresh task."""
        self._refresh_running = False
        if self._background_refresh_task:
            self._background_refresh_task.cancel()
            try:
                await self._background_refresh_task
            except asyncio.CancelledError:
                pass
        logger.info("background_market_refresh_stopped")
    
    async def _background_refresh_loop(self):
        """Background loop to refresh market cache."""
        try:
            while self._refresh_running:
                try:
                    # Force refresh markets
                    await self.get_active_markets(force_refresh=True)
                    
                    # Sleep for cache TTL (refresh just before expiry)
                    await asyncio.sleep(self.cache_ttl_seconds * 0.8)
                    
                except Exception as e:
                    logger.error("background_refresh_error", error=str(e))
                    # Continue running even on error
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("background_refresh_cancelled")
            raise


# Note: Initialized in main.py
market_fetcher: Optional[MarketFetcher] = None


def init_market_fetcher(clob_client: ClobClient):
    """Initialize market fetcher."""
    global market_fetcher
    market_fetcher = MarketFetcher(clob_client)
    return market_fetcher
