"""Fast order execution on Polymarket - SPEED OPTIMIZED."""
import asyncio
import structlog
from typing import Optional, Dict
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from decimal import Decimal
import time

from edge_detector import Edge
from config import config
from rate_limiter import get_rate_limiter
from survival_brain import SurvivalBrain

logger = structlog.get_logger()


class OrderExecutionError(Exception):
    """Base exception for order execution errors."""
    pass


class InsufficientBalanceError(OrderExecutionError):
    """Raised when account has insufficient balance."""
    pass


class InvalidOrderError(OrderExecutionError):
    """Raised when order parameters are invalid."""
    pass


class NetworkError(OrderExecutionError):
    """Raised for network/connectivity issues."""
    pass


class ExecutionEngine:
    """
    Ultra-fast order execution.
    
    Goal: <100ms from edge detection to order placement.
    """
    
    def __init__(self, clob_client: ClobClient, resolution_tracker=None, pnl_calc=None, survival_brain: Optional[SurvivalBrain] = None):
        self.client = clob_client
        self.resolution_tracker = resolution_tracker  # Optional: set after init
        self.pnl_calculator = pnl_calc  # Optional: PnL calculator
        self.telegram_alerter = None  # Optional: Telegram alerts
        self.survival_brain = survival_brain  # Optional: Survival brain for adaptive position sizing
        self.active_positions = {}  # market_id -> position info
        self.closed_positions = []  # Historical positions
        self.execution_times = []  # Track execution latency
        
        # Performance metrics (merged from speed_engine)
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        
        # Speed metrics (merged from speed_engine)
        self.fastest_trade_ms = float('inf')
        self.slowest_trade_ms = 0.0
        
        # Balance caching (30-second cache to avoid excessive API calls)
        self._cached_balance: Optional[float] = None
        self._balance_cache_time: Optional[datetime] = None
        self._balance_cache_duration = timedelta(seconds=30)
        
        # Retry statistics
        self.retry_stats = {
            'total_retries': 0,
            'successful_retries': 0,
            'failed_after_retries': 0,
            'network_errors': 0,
            'balance_errors': 0,
            'invalid_order_errors': 0
        }
        
    def _classify_error(self, error: Exception) -> OrderExecutionError:
        """
        Classify exception into retry-able or non-retry-able error types.
        
        Args:
            error: The caught exception
            
        Returns:
            Classified OrderExecutionError subclass
        """
        error_str = str(error).lower()
        
        # Check for balance/funds errors
        if any(keyword in error_str for keyword in [
            'insufficient', 'balance', 'funds', 'not enough',
            'cannot afford', 'exceeds balance'
        ]):
            self.retry_stats['balance_errors'] += 1
            return InsufficientBalanceError(str(error))
        
        # Check for invalid order errors
        if any(keyword in error_str for keyword in [
            'invalid', 'bad request', 'validation', 'parameter',
            'token_id', 'market closed', 'price out of range'
        ]):
            self.retry_stats['invalid_order_errors'] += 1
            return InvalidOrderError(str(error))
        
        # Network/connectivity errors (retry-able)
        if any(keyword in error_str for keyword in [
            'timeout', 'connection', 'network', 'unavailable',
            'gateway', '502', '503', '504', 'ssl', 'dns'
        ]):
            self.retry_stats['network_errors'] += 1
            return NetworkError(str(error))
        
        # Default to network error for unknown exceptions (retry-able)
        self.retry_stats['network_errors'] += 1
        return NetworkError(f"Unknown error: {error}")
    
    async def _submit_order_with_retry(
        self, 
        order: OrderArgs, 
        max_retries: int = 3,
        initial_delay_ms: int = 100
    ) -> Dict:
        """
        Submit order with exponential backoff retry logic.
        
        Args:
            order: The order to submit
            max_retries: Maximum number of retry attempts (default: 3)
            initial_delay_ms: Initial delay in milliseconds (default: 100ms)
            
        Returns:
            Order result dictionary
            
        Raises:
            OrderExecutionError: If order fails after all retries
        """
        attempt = 0
        last_error = None
        
        while attempt <= max_retries:
            try:
                # Rate limit: order submission
                limiter = get_rate_limiter()
                wait_ms = await limiter.acquire_order()
                
                if wait_ms > 0:
                    logger.debug("order_rate_limited", wait_ms=round(wait_ms, 1))
                
                # Attempt order submission
                result = await self.client.create_order(order)
                
                # Success! Reset backoff
                limiter.reset_backoff()
                
                if attempt > 0:
                    # This was a retry that succeeded
                    self.retry_stats['successful_retries'] += 1
                    logger.info(
                        "order_retry_succeeded",
                        attempt=attempt,
                        total_attempts=attempt + 1
                    )
                
                return result
                
            except Exception as e:
                # Handle 429 rate limit responses
                if "429" in str(e) or "too many requests" in str(e).lower():
                    limiter = get_rate_limiter()
                    limiter.handle_429("order_submit")
                
                # Classify the error
                classified_error = self._classify_error(e)
                last_error = classified_error
                
                # Don't retry for non-network errors
                if isinstance(classified_error, (InsufficientBalanceError, InvalidOrderError)):
                    logger.error(
                        "order_failed_no_retry",
                        error_type=type(classified_error).__name__,
                        error=str(classified_error),
                        attempt=attempt
                    )
                    raise classified_error
                
                # Network error - retry if attempts remain
                if attempt < max_retries:
                    # Calculate exponential backoff delay
                    delay_ms = initial_delay_ms * (2 ** attempt)
                    delay_sec = delay_ms / 1000.0
                    
                    self.retry_stats['total_retries'] += 1
                    
                    logger.warning(
                        "order_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error_type=type(classified_error).__name__,
                        error=str(e),
                        retry_delay_ms=delay_ms
                    )
                    
                    # Wait before retry
                    await asyncio.sleep(delay_sec)
                    attempt += 1
                else:
                    # Max retries exceeded
                    self.retry_stats['failed_after_retries'] += 1
                    logger.error(
                        "order_failed_after_retries",
                        total_attempts=attempt + 1,
                        error_type=type(classified_error).__name__,
                        error=str(classified_error)
                    )
                    raise classified_error
        
        # Should never reach here, but raise last error if we do
        raise last_error if last_error else NetworkError("Unknown error in retry logic")
    
    async def execute_edge(self, edge: Edge) -> Optional[Dict]:
        """
        Execute a detected edge with SPEED.
        
        Steps:
        1. Check survival brain (should we take this trade?)
        2. Fetch/update balance (cached)
        3. Calculate position size (with survival modifier)
        4. Create order
        5. Submit order
        6. Track position
        
        Target: <100ms total
        """
        start_time = datetime.now()
        
        try:
            # 1. Check survival brain before taking trade
            if self.survival_brain:
                should_take, reason = self.survival_brain.should_take_trade(
                    edge=edge.edge_pct,
                    market_type="btc_5m",  # Market type for pattern tracking
                    hour=datetime.now().hour
                )
                
                if not should_take:
                    logger.info(
                        "trade_rejected_by_survival_brain",
                        edge_pct=round(edge.edge_pct, 2),
                        reason=reason
                    )
                    return None
            
            # 2. Check if we're at max concurrent positions
            if len(self.active_positions) >= config.max_concurrent_positions:
                logger.warning(
                    "max_positions_reached",
                    current=len(self.active_positions),
                    max=config.max_concurrent_positions
                )
                return None
            
            # 3. Fetch balance (uses cache if recent, <30s old)
            await self._get_balance()
            
            # 4. Calculate position size (uses cached balance + survival modifier)
            position_size = self._calculate_position_size(edge)
            
            if position_size <= 0:
                logger.warning("position_size_too_small", edge=str(edge))
                return None
            
            # 4. Create order
            order = self._create_order(edge, position_size)
            
            # 5. Submit order with retry logic (FAST!)
            result = await self._submit_order_with_retry(order)
            
            # 6. Track execution time
            execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000
            self.execution_times.append(execution_time_ms)
            
            # Update speed metrics (merged from speed_engine)
            self._update_speed_metrics(execution_time_ms)
            
            # Keep last 100 executions for stats
            if len(self.execution_times) > 100:
                self.execution_times.pop(0)
            
            # 7. Track position
            opened_at = datetime.now()
            expected_resolution = opened_at + timedelta(minutes=5, seconds=30)  # 5min + 30s buffer
            
            position_info = {
                'market_id': edge.market_id,
                'direction': edge.direction,
                'size': position_size,
                'entry_price': edge.market_yes_price if edge.direction == "YES" else edge.market_no_price,
                'btc_price': edge.current_price,
                'edge_pct': edge.edge_pct,
                'opened_at': opened_at,
                'expected_resolution_at': expected_resolution,
                'order_id': result.get('orderID')
            }
            
            self.active_positions[edge.market_id] = position_info
            self.total_trades += 1
            
            # 8. Register position with resolution tracker
            if self.resolution_tracker:
                self.resolution_tracker.track_position(position_info)
            
            logger.info(
                "order_executed",
                market_id=edge.market_id,
                direction=edge.direction,
                size=position_size,
                edge_pct=round(edge.edge_pct, 2),
                execution_time_ms=round(execution_time_ms, 2),
                order_id=result.get('orderID')
            )
            
            # Send trade alert
            if self.telegram_alerter:
                await self.telegram_alerter.send_alert(
                    f"📊 <b>Trade Executed</b>\n\n"
                    f"Direction: <b>{edge.direction}</b>\n"
                    f"Size: <b>${position_size:.2f}</b>\n"
                    f"Edge: <b>{edge.edge_pct:.2f}%</b>\n"
                    f"Entry Price: <b>{position_info['entry_price']:.4f}</b>\n"
                    f"BTC Price: <b>${edge.current_price:,.2f}</b>\n"
                    f"Execution: <b>{execution_time_ms:.0f}ms</b>\n"
                    f"Market: <code>{edge.market_id[:40]}...</code>",
                    alert_type="trade"  # Rate limited to 1 per 10 seconds
                )
            
            return position_info
            
        except InsufficientBalanceError as e:
            logger.error(
                "execution_failed_insufficient_balance",
                edge=str(edge),
                error=str(e),
                balance=self.get_current_balance()
            )
            return None
            
        except InvalidOrderError as e:
            logger.error(
                "execution_failed_invalid_order",
                edge=str(edge),
                error=str(e)
            )
            return None
            
        except NetworkError as e:
            logger.error(
                "execution_failed_network_error",
                edge=str(edge),
                error=str(e),
                retry_stats=self.retry_stats
            )
            return None
            
        except Exception as e:
            logger.error(
                "execution_failed_unexpected",
                edge=str(edge),
                error=str(e),
                error_type=type(e).__name__
            )
            return None
    
    async def _get_balance(self) -> float:
        """
        Get current USDC balance from Polygon wallet or Polymarket.
        
        Uses 30-second caching to avoid excessive API calls.
        Falls back to config.initial_bankroll if API fails.
        
        Returns:
            Current USDC balance in USD
        """
        # Check cache first
        now = datetime.now()
        if (self._cached_balance is not None and 
            self._balance_cache_time is not None and
            now - self._balance_cache_time < self._balance_cache_duration):
            return self._cached_balance
        
        try:
            # Try to get balance from py-clob-client
            # The client should have a get_balance() or similar method
            # Note: py-clob-client 0.23.0+ should support balance queries
            
            # Method 1: Try direct balance query (if available)
            if hasattr(self.client, 'get_balance'):
                balance_data = await self.client.get_balance()
                if isinstance(balance_data, dict):
                    balance = float(balance_data.get('balance', 0))
                else:
                    balance = float(balance_data)
                
                self._cached_balance = balance
                self._balance_cache_time = now
                
                logger.info(
                    "balance_fetched",
                    balance=round(balance, 2),
                    source="api"
                )
                
                return balance
            
            # Method 2: Try getting USDC balance from allowances
            elif hasattr(self.client, 'get_allowances'):
                allowances = await self.client.get_allowances()
                if isinstance(allowances, dict):
                    balance = float(allowances.get('usdc', 0))
                    
                    self._cached_balance = balance
                    self._balance_cache_time = now
                    
                    logger.info(
                        "balance_fetched",
                        balance=round(balance, 2),
                        source="allowances"
                    )
                    
                    return balance
            
            # If no balance method available, fall back to config
            raise Exception("No balance API method available")
            
        except Exception as e:
            logger.warning(
                "balance_fetch_failed",
                error=str(e),
                fallback=config.initial_bankroll
            )
            
            # Fallback to config.initial_bankroll
            fallback_balance = float(config.initial_bankroll)
            
            # Cache the fallback value temporarily (5 seconds only for fallback)
            self._cached_balance = fallback_balance
            self._balance_cache_time = now - timedelta(seconds=25)  # Expires sooner
            
            return fallback_balance
    
    def _calculate_kelly_criterion(self, edge: Edge) -> float:
        """
        Calculate optimal position size using Kelly Criterion.
        
        Kelly formula: f* = (bp - q) / b
        Where:
        - b = odds received (decimal odds - 1)
        - p = probability of winning (our confidence)
        - q = probability of losing (1 - p)
        
        For Polymarket:
        - If betting YES at price 0.60, we get 1/0.60 = 1.67 decimal odds
        - If betting NO at price 0.40, we get 1/0.40 = 2.50 decimal odds
        
        Args:
            edge: The detected trading edge
            
        Returns:
            Kelly percentage of bankroll (0-100)
        """
        # Get the price we'd pay for this bet
        if edge.direction == "YES":
            bet_price = edge.market_yes_price
        else:
            bet_price = edge.market_no_price
        
        # Prevent division by zero or invalid prices
        if bet_price <= 0 or bet_price >= 1:
            logger.warning(
                "invalid_bet_price_for_kelly",
                direction=edge.direction,
                price=bet_price
            )
            return 0.0
        
        # Calculate decimal odds: payout / stake
        # For Polymarket: if we bet at 0.60, we get 1/0.60 = 1.67 back per $1
        decimal_odds = 1.0 / bet_price
        
        # b = net odds (what we win per $1 bet, minus our stake)
        b = decimal_odds - 1.0
        
        # p = our probability of winning (confidence adjusted by edge)
        # We use confidence as base probability, boosted by edge strength
        p = min(edge.confidence + (edge.edge_pct / 100), 0.95)  # Cap at 95%
        
        # q = probability of losing
        q = 1.0 - p
        
        # Kelly formula: f* = (bp - q) / b
        kelly_numerator = (b * p) - q
        kelly_fraction = kelly_numerator / b
        
        # Convert to percentage
        kelly_pct = kelly_fraction * 100
        
        # Apply fractional Kelly (e.g., half-Kelly for reduced volatility)
        fractional_kelly_pct = kelly_pct * config.kelly_fraction
        
        # Log Kelly calculation for analysis
        logger.info(
            "kelly_calculation",
            direction=edge.direction,
            bet_price=round(bet_price, 4),
            decimal_odds=round(decimal_odds, 2),
            b=round(b, 2),
            p=round(p, 3),
            q=round(q, 3),
            kelly_pct=round(kelly_pct, 2),
            kelly_fraction=config.kelly_fraction,
            fractional_kelly_pct=round(fractional_kelly_pct, 2),
            edge_pct=round(edge.edge_pct, 2),
            confidence=round(edge.confidence, 2)
        )
        
        # Return fractional Kelly (can be negative if no edge)
        return max(fractional_kelly_pct, 0.0)
    
    def _calculate_position_size(self, edge: Edge) -> float:
        """
        Calculate position size using Kelly Criterion.
        
        Process:
        1. Calculate Kelly optimal percentage
        2. Apply fractional Kelly (default 0.5 = half-Kelly)
        3. Cap at max_bet_percent (safety limit)
        4. Apply survival brain modifier (adaptive sizing)
        5. Convert to dollar amount based on real balance
        6. Enforce minimum bet size
        
        Returns:
            Position size in USD
        """
        # Calculate Kelly percentage
        kelly_pct = self._calculate_kelly_criterion(edge)
        
        # Cap at max_bet_percent (safety limit)
        size_pct = min(kelly_pct, config.max_bet_percent)
        
        # Apply survival brain modifier (adaptive position sizing)
        survival_modifier = 1.0
        if self.survival_brain:
            survival_modifier = self.survival_brain.get_position_size_modifier()
            size_pct = size_pct * survival_modifier
        
        # Get real balance (uses cached value if recent)
        # Note: This is now synchronous, but uses cached balance
        # The cache is updated asynchronously during execute_edge
        balance = self._cached_balance if self._cached_balance is not None else float(config.initial_bankroll)
        
        # Convert to dollar amount
        size_usd = balance * (size_pct / 100)
        
        # Log final position sizing decision
        logger.info(
            "position_sizing",
            kelly_pct=round(kelly_pct, 2),
            capped_pct=round(size_pct, 2),
            survival_modifier=round(survival_modifier, 2),
            balance=round(balance, 2),
            size_usd=round(size_usd, 2),
            was_capped=kelly_pct > config.max_bet_percent
        )
        
        # Enforce minimum
        if size_usd < 10:  # Minimum $10 bet
            logger.info(
                "position_too_small",
                size_usd=round(size_usd, 2),
                min_required=10
            )
            return 0
        
        return round(size_usd, 2)
    
    def _create_order(self, edge: Edge, size_usd: float) -> OrderArgs:
        """Create Polymarket order from edge."""
        
        # Determine which token to buy (YES or NO)
        token_id = edge.market_id  # TODO: Map to actual token ID
        
        # Price we're willing to pay
        # For YES: use current YES price + small buffer for execution
        # For NO: use current NO price + small buffer
        if edge.direction == "YES":
            price = min(edge.market_yes_price + 0.01, 0.99)  # Small buffer, cap at 0.99
        else:
            price = min(edge.market_no_price + 0.01, 0.99)
        
        # Create order
        order = OrderArgs(
            token_id=token_id,
            price=Decimal(str(price)),
            size=Decimal(str(size_usd)),
            side="BUY",
            orderType=OrderType.GTC  # Good Till Cancelled
        )
        
        return order
    
    def get_position_count(self) -> int:
        """Get current number of active positions."""
        return len(self.active_positions)
    
    def get_avg_execution_time_ms(self) -> Optional[float]:
        """Get average execution time in milliseconds."""
        if not self.execution_times:
            return None
        return sum(self.execution_times) / len(self.execution_times)
    
    async def close_position(self, market_id: str, pnl: float = 0.0, won: bool = False):
        """
        Close/remove a position (after market resolves).
        
        Args:
            market_id: Market identifier
            pnl: Profit/loss for this position
            won: Whether position was profitable
        """
        if market_id in self.active_positions:
            position = self.active_positions[market_id]
            position['closed_at'] = datetime.now()
            position['pnl'] = pnl
            position['won'] = won
            
            # Update metrics
            self.total_pnl += pnl
            if won:
                self.wins += 1
            else:
                self.losses += 1
            
            # Record realized PnL in calculator
            if self.pnl_calculator:
                self.pnl_calculator.record_realized_pnl(pnl)
            
            # Record trade result in survival brain
            if self.survival_brain:
                self.survival_brain.record_trade_result({
                    'timestamp': position['closed_at'].isoformat(),
                    'market_type': 'btc_5m',
                    'edge': position.get('edge_pct', 0.0) / 100,  # Convert to decimal
                    'amount': position.get('size', 0.0),
                    'pnl': pnl,
                    'won': won
                })
            
            # Move to closed positions
            self.closed_positions.append(position)
            
            # Keep last 100 closed positions
            if len(self.closed_positions) > 100:
                self.closed_positions.pop(0)
            
            del self.active_positions[market_id]
            
            # Untrack from resolution tracker (if not already done by tracker)
            if self.resolution_tracker:
                self.resolution_tracker.untrack_position(market_id)
            
            logger.info(
                "position_closed",
                market_id=market_id,
                pnl=round(pnl, 2),
                won=won,
                total_pnl=round(self.total_pnl, 2)
            )
            
            # Send position resolved alert
            if self.telegram_alerter:
                emoji = "✅" if won else "❌"
                result_text = "WIN" if won else "LOSS"
                pnl_sign = "+" if pnl >= 0 else ""
                
                # Calculate hold time
                hold_time = None
                if 'opened_at' in position and position['closed_at']:
                    hold_time = (position['closed_at'] - position['opened_at']).total_seconds() / 60
                
                await self.telegram_alerter.send_alert(
                    f"{emoji} <b>Position Resolved - {result_text}</b>\n\n"
                    f"P&L: <b>{pnl_sign}${pnl:.2f}</b>\n"
                    f"Direction: <b>{position.get('direction', 'N/A')}</b>\n"
                    f"Size: <b>${position.get('size', 0):.2f}</b>\n"
                    f"Hold Time: <b>{hold_time:.1f} min</b>\n"
                    f"Total P&L: <b>${self.total_pnl:.2f}</b>\n"
                    f"Win Rate: <b>{self.get_win_rate():.1f}%</b>",
                    alert_type="position"  # Rate limited to 1 per 10 seconds
                )
    
    def set_resolution_tracker(self, tracker):
        """
        Set the resolution tracker (after initialization).
        
        Args:
            tracker: ResolutionTracker instance
        """
        self.resolution_tracker = tracker
        logger.info("resolution_tracker_attached")
    
    def set_pnl_calculator(self, calculator):
        """
        Set the PnL calculator (after initialization).
        
        Args:
            calculator: PnLCalculator instance
        """
        self.pnl_calculator = calculator
        logger.info("pnl_calculator_attached")
    
    def set_telegram_alerter(self, alerter):
        """
        Set the Telegram alerter (after initialization).
        
        Args:
            alerter: TelegramAlerter instance
        """
        self.telegram_alerter = alerter
        logger.info("telegram_alerter_attached")
    
    def set_survival_brain(self, brain: SurvivalBrain):
        """
        Set the survival brain (after initialization).
        
        Args:
            brain: SurvivalBrain instance
        """
        self.survival_brain = brain
        logger.info("survival_brain_attached")
    
    def get_active_positions(self) -> Dict:
        """Get all active positions."""
        return self.active_positions
    
    def _update_speed_metrics(self, execution_ms: float):
        """Update speed performance metrics (merged from speed_engine)."""
        if execution_ms < self.fastest_trade_ms:
            self.fastest_trade_ms = execution_ms
        
        if execution_ms > self.slowest_trade_ms:
            self.slowest_trade_ms = execution_ms
    
    def get_win_rate(self) -> float:
        """Calculate win rate percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.wins / self.total_trades) * 100
    
    def get_current_balance(self) -> float:
        """
        Get current cached balance.
        
        Returns cached balance or config.initial_bankroll if no cache.
        Use this for synchronous status checks without API calls.
        """
        return self._cached_balance if self._cached_balance is not None else float(config.initial_bankroll)
    
    def get_balance_cache_age(self) -> Optional[float]:
        """
        Get age of cached balance in seconds.
        
        Returns:
            Age in seconds, or None if no cache
        """
        if self._balance_cache_time is None:
            return None
        
        return (datetime.now() - self._balance_cache_time).total_seconds()
    
    def get_status(self) -> Dict:
        """
        Get comprehensive execution engine status (merged from speed_engine).
        
        Returns:
            Dict with performance metrics, positions, speed stats, balance, retry stats, and resolution stats
        """
        # Get rate limiter stats
        limiter = get_rate_limiter()
        rate_limit_stats = limiter.get_stats()
        
        status = {
            # Trading metrics
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': round(self.get_win_rate(), 2),
            'total_pnl': round(self.total_pnl, 2),
            
            # Position tracking
            'active_positions': len(self.active_positions),
            'closed_positions': len(self.closed_positions),
            
            # Speed metrics
            'avg_execution_ms': round(self.get_avg_execution_time_ms() or 0, 2),
            'fastest_trade_ms': round(self.fastest_trade_ms, 2) if self.fastest_trade_ms != float('inf') else 0,
            'slowest_trade_ms': round(self.slowest_trade_ms, 2),
            
            # Balance
            'balance': round(self.get_current_balance(), 2),
            'balance_cache_age_sec': round(self.get_balance_cache_age() or 0, 1),
            
            # Retry statistics
            'retry_stats': self.retry_stats.copy(),
            
            # Rate limiting stats
            'rate_limiting': rate_limit_stats
        }
        
        # Add resolution tracker stats if available
        if self.resolution_tracker:
            status['resolution_stats'] = self.resolution_tracker.get_stats()
        
        return status


# Note: Initialized in main.py with client
execution_engine: Optional[ExecutionEngine] = None


def init_execution_engine(clob_client: ClobClient):
    """Initialize execution engine."""
    global execution_engine
    execution_engine = ExecutionEngine(clob_client)
    return execution_engine
