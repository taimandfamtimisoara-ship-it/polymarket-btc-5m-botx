"""Speed-optimized trading engine - BUILT FOR 5M MARKETS."""
import asyncio
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from collections import deque
import structlog

from .price_feed import price_feed
from .config import settings

logger = structlog.get_logger()


class SpeedEngine:
    """
    Ultra-fast trading engine for 5-minute markets.
    
    Strategy:
    - Track BTC price momentum (last 30 seconds)
    - Compare to Polymarket 5m market odds
    - If edge detected → Execute in <100ms
    - High volume, simple logic, speed wins
    """
    
    def __init__(self, polymarket_client, telegram):
        self.polymarket = polymarket_client
        self.telegram = telegram
        
        # Price tracking (last 60 data points = ~1 min of data)
        self.price_history = deque(maxlen=60)
        
        # Position tracking
        self.open_positions = []
        self.closed_positions = []
        
        # Performance metrics
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.bankroll = settings.initial_bankroll
        
        # Speed metrics
        self.avg_execution_time_ms = 0.0
        self.fastest_trade_ms = float('inf')
        self.slowest_trade_ms = 0.0
        
        # Register price update callback
        price_feed.register_callback(self._on_price_update)
        
    async def _on_price_update(self, price: float, change_pct: float):
        """Handle real-time price updates."""
        self.price_history.append({
            'price': price,
            'timestamp': datetime.now(),
            'change_pct': change_pct
        })
    
    def get_momentum(self) -> Optional[str]:
        """
        Get current price momentum.
        
        Returns: 'UP', 'DOWN', or None
        """
        if len(self.price_history) < 10:
            return None
        
        # Compare last 30 seconds
        recent = list(self.price_history)[-30:]
        
        if len(recent) < 2:
            return None
        
        # Calculate trend
        start_price = recent[0]['price']
        end_price = recent[-1]['price']
        
        change_pct = ((end_price - start_price) / start_price) * 100
        
        # Threshold: 0.05% = clear momentum
        if change_pct > 0.05:
            return 'UP'
        elif change_pct < -0.05:
            return 'DOWN'
        else:
            return None
    
    async def scan_and_execute(self):
        """
        Scan for 5m markets and execute if edge found.
        
        This runs continuously in a loop.
        """
        while True:
            try:
                start_time = datetime.now()
                
                # Get current momentum
                momentum = self.get_momentum()
                
                if not momentum:
                    await asyncio.sleep(0.5)  # Check every 500ms
                    continue
                
                # Get 5m markets from Polymarket
                markets = await self._get_5m_markets()
                
                for market in markets:
                    # Check if we already have position in this market
                    if self._has_position(market['market_id']):
                        continue
                    
                    # Calculate edge
                    edge_data = self._calculate_edge(market, momentum)
                    
                    if edge_data and edge_data['edge'] >= settings.min_edge:
                        # EXECUTE
                        await self._execute_trade(edge_data, start_time)
                
                # Limit scan rate
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error("scan_error", error=str(e), exc_info=True)
                await asyncio.sleep(1)
    
    async def _get_5m_markets(self) -> List[Dict]:
        """Get all active 5-minute BTC markets."""
        try:
            # This would call Polymarket API
            # For now, simplified
            markets = await asyncio.to_thread(
                self.polymarket.get_btc_5m_markets
            )
            return markets
        except Exception as e:
            logger.error("get_markets_failed", error=str(e))
            return []
    
    def _calculate_edge(self, market: Dict, momentum: str) -> Optional[Dict]:
        """
        Calculate edge for a 5m market.
        
        Simple logic:
        - If momentum UP + market underpricing UP → Edge on YES
        - If momentum DOWN + market underpricing DOWN → Edge on YES (for DOWN market)
        """
        question = market['question'].lower()
        yes_price = market['yes_price']
        no_price = market['no_price']
        
        # Determine market type
        if 'up' in question or 'higher' in question:
            # Market asking: Will BTC go UP?
            if momentum == 'UP':
                # We think it will go up
                edge = self._calculate_probability(momentum) - yes_price
                if edge > 0:
                    return {
                        'market_id': market['market_id'],
                        'side': 'YES',
                        'edge': edge * 100,  # Convert to %
                        'market_odds': yes_price,
                        'momentum': momentum,
                        'question': market['question']
                    }
            elif momentum == 'DOWN':
                # We think it will go down (bet NO on UP market)
                edge = self._calculate_probability(momentum) - no_price
                if edge > 0:
                    return {
                        'market_id': market['market_id'],
                        'side': 'NO',
                        'edge': edge * 100,
                        'market_odds': no_price,
                        'momentum': momentum,
                        'question': market['question']
                    }
        
        elif 'down' in question or 'lower' in question:
            # Market asking: Will BTC go DOWN?
            if momentum == 'DOWN':
                edge = self._calculate_probability(momentum) - yes_price
                if edge > 0:
                    return {
                        'market_id': market['market_id'],
                        'side': 'YES',
                        'edge': edge * 100,
                        'market_odds': yes_price,
                        'momentum': momentum,
                        'question': market['question']
                    }
            elif momentum == 'UP':
                edge = self._calculate_probability(momentum) - no_price
                if edge > 0:
                    return {
                        'market_id': market['market_id'],
                        'side': 'NO',
                        'edge': edge * 100,
                        'market_odds': no_price,
                        'momentum': momentum,
                        'question': market['question']
                    }
        
        return None
    
    def _calculate_probability(self, momentum: str) -> float:
        """
        Convert momentum to probability.
        
        For 5m markets, if we detect momentum, assign high confidence.
        """
        if momentum in ['UP', 'DOWN']:
            return 0.65  # 65% confidence in momentum continuing
        return 0.50
    
    async def _execute_trade(self, edge_data: Dict, start_time: datetime):
        """Execute trade with speed tracking."""
        try:
            # Calculate position size
            max_bet = self.bankroll * (settings.max_bet_percent / 100)
            position_size = min(max_bet, self.bankroll * 0.1)  # Max 10% per trade
            
            # Place order
            order = await asyncio.to_thread(
                self.polymarket.place_order,
                market_id=edge_data['market_id'],
                side=edge_data['side'],
                amount=position_size,
                price=edge_data['market_odds']
            )
            
            if order:
                # Calculate execution time
                execution_time = (datetime.now() - start_time).total_seconds() * 1000
                
                # Update speed metrics
                self._update_speed_metrics(execution_time)
                
                # Record position
                position = {
                    'market_id': edge_data['market_id'],
                    'question': edge_data['question'],
                    'side': edge_data['side'],
                    'amount': position_size,
                    'entry_odds': edge_data['market_odds'],
                    'edge': edge_data['edge'],
                    'momentum': edge_data['momentum'],
                    'opened_at': datetime.now(),
                    'execution_time_ms': execution_time
                }
                
                self.open_positions.append(position)
                self.total_trades += 1
                self.bankroll -= position_size
                
                # Alert
                await self.telegram.send_alert(
                    f"⚡ TRADE EXECUTED ({execution_time:.0f}ms)\n\n"
                    f"{edge_data['question']}\n\n"
                    f"Side: {edge_data['side']}\n"
                    f"Amount: ${position_size:.2f}\n"
                    f"Edge: {edge_data['edge']:.1f}%\n"
                    f"Momentum: {edge_data['momentum']}\n"
                    f"Bankroll: ${self.bankroll:.2f}"
                )
                
                logger.info(
                    "trade_executed",
                    market_id=edge_data['market_id'],
                    execution_ms=execution_time,
                    edge=edge_data['edge']
                )
        
        except Exception as e:
            logger.error("trade_execution_failed", error=str(e), exc_info=True)
    
    def _update_speed_metrics(self, execution_ms: float):
        """Update speed performance metrics."""
        if execution_ms < self.fastest_trade_ms:
            self.fastest_trade_ms = execution_ms
        
        if execution_ms > self.slowest_trade_ms:
            self.slowest_trade_ms = execution_ms
        
        # Calculate moving average
        n = self.total_trades
        self.avg_execution_time_ms = (
            (self.avg_execution_time_ms * (n - 1) + execution_ms) / n
        )
    
    def _has_position(self, market_id: str) -> bool:
        """Check if we already have a position in this market."""
        return any(p['market_id'] == market_id for p in self.open_positions)
    
    async def check_resolutions(self):
        """Check for market resolutions and update P&L."""
        for position in self.open_positions[:]:  # Copy to iterate safely
            try:
                # Check if market resolved
                market = await asyncio.to_thread(
                    self.polymarket.get_market_by_id,
                    position['market_id']
                )
                
                if not market:
                    # Market resolved
                    # For now, simplified - would need actual resolution data
                    self.open_positions.remove(position)
                    # Move to closed
                    self.closed_positions.append(position)
            
            except Exception as e:
                logger.error("resolution_check_failed", error=str(e))
    
    def get_status(self) -> Dict:
        """Get current engine status (for dashboard)."""
        return {
            'bankroll': self.bankroll,
            'initial_bankroll': settings.initial_bankroll,
            'pnl': self.total_pnl,
            'pnl_percent': (self.total_pnl / settings.initial_bankroll) * 100 if settings.initial_bankroll > 0 else 0,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': (self.wins / self.total_trades) * 100 if self.total_trades > 0 else 0,
            'open_positions': len(self.open_positions),
            'avg_execution_ms': self.avg_execution_time_ms,
            'fastest_trade_ms': self.fastest_trade_ms if self.fastest_trade_ms != float('inf') else 0,
            'slowest_trade_ms': self.slowest_trade_ms,
            'current_price': price_feed.get_current_price(),
            'feed_latency_ms': price_feed.get_latency_ms(),
            'momentum': self.get_momentum()
        }
