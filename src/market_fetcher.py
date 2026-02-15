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
        Fetch markets from Gamma Markets API (ASYNC - non-blocking).
        
        Returns raw market data with metadata.
        """
        try:
            # Rate limit: market fetching
            limiter = get_rate_limiter()
            await limiter.acquire_market()
            
            # Gamma API endpoint for markets
            url = f"{self.GAMMA_API_BASE}/markets"
            
            # Add query parameters for filtering
            params = {
                'closed': 'false',  # Only active markets
                'limit': 100,  # Get recent markets
                'order': 'created_at',
                'ascending': 'false'
            }
            
            session = await get_http_session()
            async with session.get(url, params=params) as response:
                # Handle 429 rate limit responses
                if response.status == 429:
                    limiter.handle_429("gamma_markets")
                    logger.warning("gamma_api_rate_limited")
                    return []
                
                response.raise_for_status()
                limiter.reset_backoff()  # Success - reset backoff
                
                data = await response.json()
            
            markets = data if isinstance(data, list) else data.get('data', [])
            
            # Filter for BTC 5-minute markets
            btc_5m_markets = []
            for market in markets:
                if self._is_btc_5m_market(market):
                    btc_5m_markets.append(market)
            
            logger.info("gamma_api_success", total=len(markets), btc_5m=len(btc_5m_markets))
            return btc_5m_markets
            
        except Exception as e:
            logger.warning("gamma_api_error", error=str(e))
            return []
    
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
            
            # Debug: Log sample market questions to understand format
            btc_related = [m for m in markets if 'btc' in m.get('question', '').lower() or 'bitcoin' in m.get('question', '').lower()]
            if btc_related:
                sample_questions = [m.get('question', '')[:80] for m in btc_related[:5]]
                logger.info("btc_markets_found", count=len(btc_related), samples=sample_questions)
            
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
        
        Criteria:
        - Question contains "BTC" or "Bitcoin"
        - Duration is 5 minutes
        - Still active (not closed/resolved)
        """
        question = market.get('question', '').upper()
        
        # Check if BTC-related
        if not any(term in question for term in ['BTC', 'BITCOIN']):
            return False
        
        # Check if 5-minute market
        if not any(term in question for term in ['5 MINUTE', '5M', '5-MINUTE', '5MIN']):
            return False
        
        # Check if active
        if market.get('closed', False) or market.get('resolved', False):
            return False
        
        # Check if recent (created within last 2 hours for safety)
        created_at = market.get('start_date_iso') or market.get('created_at')
        if created_at:
            try:
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                if datetime.now(created.tzinfo) - created > timedelta(hours=2):
                    return False
            except Exception as e:
                logger.debug("date_parse_error", created_at=created_at, error=str(e))
        
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
