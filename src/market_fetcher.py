"""Fetch active 5-minute BTC markets from Polymarket."""
import asyncio
import structlog
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient

logger = structlog.get_logger()


class MarketFetcher:
    """
    Fetches active 5-minute BTC markets from Polymarket.
    
    Filters:
    - Only BTC markets
    - Only 5-minute duration
    - Only active (not resolved)
    - Only recent (created within last hour)
    """
    
    def __init__(self, clob_client: ClobClient):
        self.client = clob_client
        self.cached_markets = []
        self.last_fetch = None
        self.cache_ttl_seconds = 30  # Refresh cache every 30s
        
    async def get_active_markets(self, force_refresh: bool = False) -> List[Dict]:
        """
        Get active 5-minute BTC markets.
        
        Returns list of markets with:
        - id: Market ID
        - question: Market question
        - baseline_price: BTC price when market was created
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
            # Fetch markets from Polymarket
            # Note: API specifics depend on py-clob-client implementation
            # This is a template - adjust based on actual API
            
            all_markets = await self._fetch_all_markets()
            
            # Filter for 5-minute BTC markets
            btc_5m_markets = []
            
            for market in all_markets:
                if self._is_btc_5m_market(market):
                    # Parse market data
                    parsed = self._parse_market(market)
                    if parsed:
                        btc_5m_markets.append(parsed)
            
            # Update cache
            self.cached_markets = btc_5m_markets
            self.last_fetch = datetime.now()
            
            logger.info(
                "markets_fetched",
                total=len(all_markets),
                btc_5m=len(btc_5m_markets)
            )
            
            return btc_5m_markets
            
        except Exception as e:
            logger.error("market_fetch_failed", error=str(e))
            return self.cached_markets  # Return stale cache on error
    
    async def _fetch_all_markets(self) -> List[Dict]:
        """Fetch all markets from Polymarket."""
        try:
            # Use Polymarket API to get markets
            # Endpoint: /markets (check py-clob-client docs)
            
            # Placeholder - adjust based on actual API
            markets = await self.client.get_markets()
            return markets if markets else []
            
        except Exception as e:
            logger.error("polymarket_api_error", error=str(e))
            return []
    
    def _is_btc_5m_market(self, market: Dict) -> bool:
        """
        Check if market is a 5-minute BTC market.
        
        Criteria:
        - Question contains "BTC" or "Bitcoin"
        - Duration is 5 minutes
        - Still active
        """
        question = market.get('question', '').upper()
        
        # Check if BTC-related
        if not any(term in question for term in ['BTC', 'BITCOIN']):
            return False
        
        # Check if 5-minute market
        # Look for "5 MINUTE" or "5M" in question
        if not any(term in question for term in ['5 MINUTE', '5M', '5-MINUTE']):
            return False
        
        # Check if active
        if market.get('closed', False):
            return False
        
        # Check if recent (created within last hour)
        created_at = market.get('created_at')
        if created_at:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if datetime.now() - created > timedelta(hours=1):
                return False
        
        return True
    
    def _parse_market(self, market: Dict) -> Optional[Dict]:
        """
        Parse market data into our format.
        
        Extracts:
        - Baseline BTC price from question
        - Current YES/NO prices
        - Timestamps
        """
        try:
            market_id = market.get('id')
            question = market.get('question')
            
            # Extract baseline price from question
            # Example: "Will BTC be above $95,000 in 5 minutes?"
            baseline_price = self._extract_baseline_price(question)
            
            if not baseline_price:
                logger.warning("no_baseline_price", question=question)
                return None
            
            # Get current token prices
            # Placeholder - adjust based on API structure
            yes_price = market.get('yes_price', 0.5)
            no_price = 1 - yes_price  # NO price = 1 - YES price
            
            # Timestamps
            created_at = market.get('created_at')
            end_date = market.get('end_date_iso')
            
            return {
                'id': market_id,
                'question': question,
                'baseline_price': baseline_price,
                'yes_price': yes_price,
                'no_price': no_price,
                'created_at': created_at,
                'closes_at': end_date
            }
            
        except Exception as e:
            logger.error("market_parse_error", error=str(e), market=market)
            return None
    
    def _extract_baseline_price(self, question: str) -> Optional[float]:
        """
        Extract BTC baseline price from question.
        
        Examples:
        - "Will BTC be above $95,000 in 5 minutes?" -> 95000
        - "BTC > $94,500 in next 5m?" -> 94500
        """
        import re
        
        # Look for price pattern: $XX,XXX or $XX,XXX.XX
        pattern = r'\$([0-9,]+(?:\.[0-9]+)?)'
        match = re.search(pattern, question)
        
        if match:
            price_str = match.group(1).replace(',', '')
            return float(price_str)
        
        return None
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """Get a specific market from cache."""
        for market in self.cached_markets:
            if market['id'] == market_id:
                return market
        return None


# Note: Initialized in main.py
market_fetcher: Optional[MarketFetcher] = None


def init_market_fetcher(clob_client: ClobClient):
    """Initialize market fetcher."""
    global market_fetcher
    market_fetcher = MarketFetcher(clob_client)
    return market_fetcher
