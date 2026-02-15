"""Real-time PnL calculation with price caching."""
import asyncio
import structlog
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient
from rate_limiter import get_rate_limiter

logger = structlog.get_logger()


class PnLCalculator:
    """
    Calculate real-time unrealized and realized PnL.
    
    Features:
    - Fetches current YES/NO prices for open positions
    - Calculates unrealized P&L: (current_price - entry_price) * position_size
    - Tracks realized P&L from closed positions
    - Caches market prices (30s TTL) to avoid excessive API calls
    """
    
    def __init__(self, clob_client: ClobClient):
        """
        Initialize PnL calculator.
        
        Args:
            clob_client: Polymarket CLOB client for fetching prices
        """
        self.client = clob_client
        
        # Price cache: {token_id: {'price': float, 'timestamp': datetime}}
        self._price_cache: Dict[str, Dict] = {}
        self._cache_ttl = timedelta(seconds=30)  # 30-second cache
        
        # Realized PnL tracking
        self.realized_pnl = 0.0
        self.closed_positions_count = 0
        
    async def get_token_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """
        Get current price for a token with caching.
        
        Args:
            token_id: Token ID to get price for
            side: "BUY" or "SELL" (default: "BUY" for midpoint)
        
        Returns:
            Current price (0.0-1.0) or None if fetch fails
        """
        # Check cache first
        cache_key = f"{token_id}_{side}"
        if cache_key in self._price_cache:
            cached = self._price_cache[cache_key]
            age = datetime.now() - cached['timestamp']
            
            if age < self._cache_ttl:
                logger.debug("price_cache_hit", token_id=token_id, side=side)
                return cached['price']
        
        # Fetch fresh price with rate limiting
        try:
            # Rate limit: price fetching
            limiter = get_rate_limiter()
            wait_ms = await limiter.acquire_price()
            
            if wait_ms > 0:
                logger.debug("price_fetch_rate_limited", wait_ms=round(wait_ms, 1))
            
            # Use midpoint for more accurate pricing
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                self.client.get_midpoint,
                token_id
            )
            
            if isinstance(result, dict):
                price = float(result.get('mid', 0.5))
            else:
                price = 0.5
            
            # Update cache
            self._price_cache[cache_key] = {
                'price': price,
                'timestamp': datetime.now()
            }
            
            limiter.reset_backoff()  # Success - reset backoff
            logger.debug("price_fetched", token_id=token_id, side=side, price=price)
            return price
            
        except Exception as e:
            # Check for 429 rate limit response
            if "429" in str(e) or "too many requests" in str(e).lower():
                limiter = get_rate_limiter()
                limiter.handle_429("price_fetch")
            
            logger.warning("price_fetch_failed", token_id=token_id, error=str(e))
            
            # Try to return stale cache
            if cache_key in self._price_cache:
                logger.info("using_stale_price_cache", token_id=token_id)
                return self._price_cache[cache_key]['price']
            
            return None
    
    async def calculate_position_pnl(
        self,
        position: Dict,
        market_data: Optional[Dict] = None
    ) -> Tuple[float, Optional[float]]:
        """
        Calculate P&L for a single position.
        
        Args:
            position: Position dict with:
                - direction: "YES" or "NO"
                - entry_price: Price paid (0.0-1.0)
                - size: Position size in USD
                - market_id: Market/token identifier
            market_data: Optional market data with token IDs
        
        Returns:
            Tuple of (unrealized_pnl, current_price)
        """
        try:
            # Determine which token to price
            # For simplicity, use market_id as token_id
            # In production, you'd need to map market_id -> token_id for YES/NO
            token_id = position.get('market_id')
            
            if not token_id:
                logger.warning("position_missing_market_id", position=position)
                return (0.0, None)
            
            # Get current market price
            current_price = await self.get_token_price(token_id)
            
            if current_price is None:
                logger.warning("failed_to_get_price", token_id=token_id)
                return (0.0, None)
            
            # Calculate PnL based on direction
            entry_price = position['entry_price']
            size = position['size']
            direction = position['direction']
            
            # For YES: profit if price went up
            # For NO: profit if price went down
            if direction == "YES":
                price_change = current_price - entry_price
            else:
                # NO position: inverse relationship
                price_change = entry_price - current_price
            
            # PnL = price_change * position_size
            # Since size is in USD and prices are 0-1, we need to normalize
            shares = size / entry_price  # How many shares bought
            current_value = shares * current_price
            unrealized_pnl = current_value - size
            
            return (unrealized_pnl, current_price)
            
        except Exception as e:
            logger.error(
                "pnl_calculation_error",
                position=position,
                error=str(e),
                exc_info=True
            )
            return (0.0, None)
    
    async def calculate_portfolio_pnl(self, active_positions: Dict) -> Dict:
        """
        Calculate total portfolio PnL (unrealized + realized).
        
        Args:
            active_positions: Dict of {market_id: position_info}
        
        Returns:
            Dict with:
                - unrealized_pnl: Total unrealized P&L
                - realized_pnl: Total realized P&L from closed positions
                - total_pnl: unrealized + realized
                - positions: List of positions with calculated PnL
        """
        total_unrealized = 0.0
        positions_with_pnl = []
        
        # Calculate unrealized PnL for each active position
        for market_id, position in active_positions.items():
            pnl, current_price = await self.calculate_position_pnl(position)
            
            total_unrealized += pnl
            
            # Add PnL to position data
            position_data = position.copy()
            position_data['unrealized_pnl'] = round(pnl, 2)
            position_data['current_price'] = current_price
            
            positions_with_pnl.append(position_data)
        
        # Total PnL = unrealized + realized
        total_pnl = total_unrealized + self.realized_pnl
        
        return {
            'unrealized_pnl': round(total_unrealized, 2),
            'realized_pnl': round(self.realized_pnl, 2),
            'total_pnl': round(total_pnl, 2),
            'positions': positions_with_pnl
        }
    
    def record_realized_pnl(self, pnl: float):
        """
        Record realized P&L from a closed position.
        
        Args:
            pnl: Profit/loss from closed position
        """
        self.realized_pnl += pnl
        self.closed_positions_count += 1
        
        logger.info(
            "realized_pnl_recorded",
            pnl=round(pnl, 2),
            total_realized=round(self.realized_pnl, 2),
            closed_count=self.closed_positions_count
        )
    
    def get_stats(self) -> Dict:
        """
        Get PnL calculator statistics.
        
        Returns:
            Dict with stats about price cache and realized PnL
        """
        return {
            'realized_pnl': round(self.realized_pnl, 2),
            'closed_positions': self.closed_positions_count,
            'price_cache_size': len(self._price_cache),
            'cache_ttl_seconds': int(self._cache_ttl.total_seconds())
        }
    
    def clear_cache(self):
        """Clear price cache (useful for testing or manual refresh)."""
        self._price_cache.clear()
        logger.info("price_cache_cleared")


# Global instance (initialized in main.py)
pnl_calculator: Optional[PnLCalculator] = None


def init_pnl_calculator(clob_client: ClobClient) -> PnLCalculator:
    """
    Initialize global PnL calculator instance.
    
    Args:
        clob_client: Polymarket CLOB client
    
    Returns:
        PnLCalculator instance
    """
    global pnl_calculator
    pnl_calculator = PnLCalculator(clob_client)
    logger.info("pnl_calculator_initialized")
    return pnl_calculator
