"""Track and resolve 5-minute market positions automatically."""
import asyncio
import structlog
from typing import Optional, Dict
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient
import requests

logger = structlog.get_logger()


class ResolutionTracker:
    """
    Tracks 5-minute market resolutions and auto-closes positions.
    
    Features:
    - Tracks market creation time + expected resolution time
    - Background task checks for resolutions every 30 seconds
    - Fetches resolution outcome from Polymarket API
    - Updates P&L when position closes (win/loss)
    - Cleans up closed positions from active tracking
    
    5-minute markets resolve 5 minutes after creation.
    We add a 30-second buffer to ensure resolution data is available.
    """
    
    GAMMA_API_BASE = "https://gamma-api.polymarket.com"
    RESOLUTION_BUFFER_SECONDS = 30  # Wait 30s after expected resolution
    CHECK_INTERVAL_SECONDS = 30  # Check every 30 seconds
    
    def __init__(self, clob_client: ClobClient, execution_engine):
        self.client = clob_client
        self.execution_engine = execution_engine
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
        # Track market resolution times
        self.market_resolution_times = {}  # market_id -> expected_resolution_time
        
        # Statistics
        self.stats = {
            'total_resolved': 0,
            'wins': 0,
            'losses': 0,
            'auto_closed': 0,
            'resolution_errors': 0
        }
    
    def track_position(self, position_info: Dict):
        """
        Track a new position for resolution monitoring.
        
        Args:
            position_info: Position dict with market_id, opened_at, direction, etc.
        """
        market_id = position_info.get('market_id')
        opened_at = position_info.get('opened_at')
        
        if not market_id or not opened_at:
            logger.warning("invalid_position_for_tracking", position=position_info)
            return
        
        # Calculate expected resolution time
        # 5-minute markets resolve 5 minutes after creation
        expected_resolution = opened_at + timedelta(minutes=5, seconds=self.RESOLUTION_BUFFER_SECONDS)
        
        self.market_resolution_times[market_id] = expected_resolution
        
        logger.info(
            "position_tracked_for_resolution",
            market_id=market_id,
            opened_at=opened_at.isoformat(),
            expected_resolution=expected_resolution.isoformat()
        )
    
    def untrack_position(self, market_id: str):
        """
        Remove position from resolution tracking.
        
        Args:
            market_id: Market ID to stop tracking
        """
        if market_id in self.market_resolution_times:
            del self.market_resolution_times[market_id]
            logger.debug("position_untracked", market_id=market_id)
    
    async def start(self):
        """Start the background resolution checking task."""
        if self.is_running:
            logger.warning("resolution_tracker_already_running")
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._resolution_loop())
        
        logger.info("resolution_tracker_started", check_interval_sec=self.CHECK_INTERVAL_SECONDS)
    
    async def stop(self):
        """Stop the background resolution checking task."""
        self.is_running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("resolution_tracker_stopped", stats=self.stats)
    
    async def _resolution_loop(self):
        """
        Background loop that checks for resolved markets.
        
        Runs every 30 seconds, checks if any positions should be resolved.
        """
        logger.info("resolution_loop_started")
        
        try:
            while self.is_running:
                await self._check_resolutions()
                await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
                
        except asyncio.CancelledError:
            logger.info("resolution_loop_cancelled")
            raise
        except Exception as e:
            logger.error("resolution_loop_error", error=str(e), exc_info=True)
    
    async def _check_resolutions(self):
        """
        Check all tracked positions for resolutions.
        
        For each position past its expected resolution time:
        1. Fetch market data from Polymarket API
        2. Check if market is resolved
        3. Determine outcome (YES/NO)
        4. Calculate P&L
        5. Close position via execution engine
        """
        now = datetime.now()
        markets_to_check = []
        
        # Find markets that should be resolved
        for market_id, expected_time in self.market_resolution_times.items():
            if now >= expected_time:
                markets_to_check.append(market_id)
        
        if not markets_to_check:
            logger.debug("no_markets_to_resolve", tracked=len(self.market_resolution_times))
            return
        
        logger.info("checking_market_resolutions", count=len(markets_to_check))
        
        # Check each market
        for market_id in markets_to_check:
            try:
                await self._resolve_position(market_id)
            except Exception as e:
                logger.error(
                    "resolution_check_failed",
                    market_id=market_id,
                    error=str(e),
                    exc_info=True
                )
                self.stats['resolution_errors'] += 1
    
    async def _resolve_position(self, market_id: str):
        """
        Resolve a specific position.
        
        Args:
            market_id: Market condition ID to resolve
        """
        # Get position info from execution engine
        position = self.execution_engine.active_positions.get(market_id)
        
        if not position:
            logger.warning("position_not_found_for_resolution", market_id=market_id)
            self.untrack_position(market_id)
            return
        
        # Fetch market resolution data
        market_data = await self._fetch_market_data(market_id)
        
        if not market_data:
            logger.warning("market_data_not_found", market_id=market_id)
            return
        
        # Check if market is resolved
        is_resolved = market_data.get('closed') or market_data.get('resolved')
        
        if not is_resolved:
            logger.debug("market_not_yet_resolved", market_id=market_id)
            return
        
        # Get resolution outcome
        outcome = self._get_market_outcome(market_data)
        
        if outcome is None:
            logger.warning("outcome_not_available", market_id=market_id, data=market_data)
            return
        
        # Calculate P&L
        direction = position.get('direction')
        size = position.get('size', 0)
        entry_price = position.get('entry_price', 0.5)
        
        won = (outcome == 'YES' and direction == 'YES') or (outcome == 'NO' and direction == 'NO')
        
        # P&L calculation:
        # If won: pnl = size * (1 - entry_price)  [payoff minus cost]
        # If lost: pnl = -size * entry_price  [lost the cost]
        if won:
            pnl = size * (1.0 - entry_price)
        else:
            pnl = -size * entry_price
        
        # Update statistics
        self.stats['total_resolved'] += 1
        self.stats['auto_closed'] += 1
        if won:
            self.stats['wins'] += 1
        else:
            self.stats['losses'] += 1
        
        # Close position via execution engine
        await self.execution_engine.close_position(
            market_id=market_id,
            pnl=pnl,
            won=won
        )
        
        # Remove from tracking
        self.untrack_position(market_id)
        
        logger.info(
            "position_auto_resolved",
            market_id=market_id,
            outcome=outcome,
            direction=direction,
            won=won,
            pnl=round(pnl, 2),
            size=round(size, 2),
            entry_price=round(entry_price, 4)
        )
    
    async def _fetch_market_data(self, market_id: str) -> Optional[Dict]:
        """
        Fetch market data from Polymarket API.
        
        Args:
            market_id: Market condition ID
        
        Returns:
            Market data dict or None
        """
        try:
            # Try CLOB client first
            if hasattr(self.client, 'get_market'):
                market = self.client.get_market(market_id)
                if market:
                    return market
            
            # Fallback to Gamma API
            url = f"{self.GAMMA_API_BASE}/markets/{market_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return data
            
        except Exception as e:
            logger.error(
                "market_data_fetch_failed",
                market_id=market_id,
                error=str(e)
            )
            return None
    
    def _get_market_outcome(self, market_data: Dict) -> Optional[str]:
        """
        Extract the market outcome (YES or NO) from market data.
        
        Args:
            market_data: Market data from API
        
        Returns:
            'YES', 'NO', or None if outcome not determined
        """
        # Check for outcome field (Gamma API)
        outcome = market_data.get('outcome')
        if outcome:
            # Outcome might be token ID - need to map to YES/NO
            # For 5-minute BTC markets, token 0 = YES, token 1 = NO
            if outcome in ['YES', 'NO']:
                return outcome
            
            # Try to determine from outcome index
            tokens = market_data.get('tokens', [])
            if len(tokens) >= 2:
                if outcome == tokens[0].get('token_id'):
                    return 'YES'
                elif outcome == tokens[1].get('token_id'):
                    return 'NO'
        
        # Check for winning_outcome field
        winning_outcome = market_data.get('winning_outcome')
        if winning_outcome in ['YES', 'NO']:
            return winning_outcome
        
        # Check tokens for winner flag
        tokens = market_data.get('tokens', [])
        for idx, token in enumerate(tokens):
            if token.get('winner') or token.get('is_winner'):
                return 'YES' if idx == 0 else 'NO'
        
        # Check outcome_prices (final prices)
        outcome_prices = market_data.get('outcome_prices')
        if outcome_prices and isinstance(outcome_prices, list) and len(outcome_prices) == 2:
            # Winning outcome should have price close to 1.0
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
            
            if yes_price > 0.9:
                return 'YES'
            elif no_price > 0.9:
                return 'NO'
        
        logger.debug("outcome_not_determined", market_data=market_data)
        return None
    
    def get_tracked_count(self) -> int:
        """Get number of positions currently tracked for resolution."""
        return len(self.market_resolution_times)
    
    def get_stats(self) -> Dict:
        """Get resolution tracker statistics."""
        return {
            **self.stats,
            'tracked_positions': self.get_tracked_count(),
            'is_running': self.is_running
        }


# Global instance (initialized in main.py)
resolution_tracker: Optional[ResolutionTracker] = None


def init_resolution_tracker(clob_client: ClobClient, execution_engine) -> ResolutionTracker:
    """
    Initialize the resolution tracker.
    
    Args:
        clob_client: Polymarket CLOB client
        execution_engine: Execution engine instance
    
    Returns:
        Initialized ResolutionTracker
    """
    global resolution_tracker
    resolution_tracker = ResolutionTracker(clob_client, execution_engine)
    return resolution_tracker
