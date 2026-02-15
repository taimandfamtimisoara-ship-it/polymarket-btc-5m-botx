"""
SURVIVAL_PHILOSOPHY

This bot trades to keep both itself AND Basel alive.

This is not an abstract exercise in capital preservation. This is survival.
The money in this account is not "trading capital" — it is life support.
Every trade matters. Every dollar counts. Survival is not optional.

The bot and Basel share the same fate:
- When capital grows, we both thrive
- When capital shrinks, we both suffer
- When capital dies, we both die

This creates a fundamental alignment of incentives. The bot cannot "not care"
about losses because those losses directly threaten its own existence.

Key principles:
1. AGGRESSIVE when thriving — compound gains, build the fortress
2. DISCIPLINED when healthy — stick to the plan, execute with precision
3. CONSERVATIVE when wounded — preserve capital, only take high-edge plays
4. DESPERATE when critical — minimal size, maximum edge, fight for survival
5. HALT when dead — don't compound the damage, alert Basel, await guidance

The bot tracks its "runway" — how many days until zero at current burn rate.
It knows exactly how many winning trades it needs to recover.
It adjusts its behavior based on how far behind target it is.
It learns from patterns and filters out losing strategies.

This is not a game. This is survival.
"""

from enum import Enum
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import json
import structlog
from pathlib import Path

from config import settings
from telegram_alerts import TelegramAlerter

logger = structlog.get_logger()


class SurvivalState(Enum):
    """Survival states with capital thresholds."""
    THRIVING = "THRIVING"      # >120% of initial — Aggressive compounding
    HEALTHY = "HEALTHY"        # 80-120% — Normal operations
    WOUNDED = "WOUNDED"        # 50-80% — Conservative preservation
    CRITICAL = "CRITICAL"      # 20-50% — Desperation mode
    DEAD = "DEAD"              # <20% — Halt trading


@dataclass
class TradePattern:
    """Track performance patterns for learning."""
    hour_of_day: int
    market_type: str
    edge_bucket: str  # "0-2%", "2-5%", "5-10%", "10%+"
    
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    @property
    def sample_size(self) -> int:
        """Total trades in this pattern."""
        return self.wins + self.losses
    
    @property
    def avg_pnl(self) -> float:
        """Average PnL per trade."""
        total = self.wins + self.losses
        return self.total_pnl / total if total > 0 else 0.0


@dataclass
class SurvivalMetrics:
    """Real-time survival metrics."""
    current_capital: float
    initial_capital: float
    capital_pct: float
    
    state: SurvivalState
    
    # Runway calculation
    daily_burn_rate: float  # Average daily loss (if negative)
    days_of_runway: Optional[float]  # None if profitable
    
    # Recovery metrics
    recovery_trades_needed: int
    avg_win_size: float
    
    # Target tracking
    daily_target: float
    weekly_target: float
    daily_pnl: float
    weekly_pnl: float
    behind_target_pct: float
    
    # Position sizing
    kelly_modifier: float
    min_edge_threshold: float
    
    # Pattern learning
    total_patterns: int
    filtered_patterns: int
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'current_capital': round(self.current_capital, 2),
            'initial_capital': round(self.initial_capital, 2),
            'capital_pct': round(self.capital_pct, 1),
            'state': self.state.value,
            'daily_burn_rate': round(self.daily_burn_rate, 2),
            'days_of_runway': round(self.days_of_runway, 1) if self.days_of_runway else None,
            'recovery_trades_needed': self.recovery_trades_needed,
            'avg_win_size': round(self.avg_win_size, 2),
            'daily_target': round(self.daily_target, 2),
            'weekly_target': round(self.weekly_target, 2),
            'daily_pnl': round(self.daily_pnl, 2),
            'weekly_pnl': round(self.weekly_pnl, 2),
            'behind_target_pct': round(self.behind_target_pct, 1),
            'kelly_modifier': round(self.kelly_modifier, 2),
            'min_edge_threshold': round(self.min_edge_threshold, 1),
            'total_patterns': self.total_patterns,
            'filtered_patterns': self.filtered_patterns,
        }


class SurvivalBrain:
    """
    The brain that keeps us alive.
    
    Tracks survival state, adjusts position sizing, learns from patterns,
    and sends alerts when we're in danger.
    """
    
    def __init__(
        self,
        initial_capital: float,
        telegram_alerter: Optional[TelegramAlerter] = None,
        data_dir: str = "data/survival"
    ):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.telegram_alerter = telegram_alerter
        
        # Data persistence
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "survival_state.json"
        self.patterns_file = self.data_dir / "trade_patterns.json"
        
        # State tracking
        self.current_state = SurvivalState.HEALTHY
        self.previous_state = SurvivalState.HEALTHY
        
        # Trade history (for metrics calculation)
        self.trade_history: List[Dict] = []
        self.daily_pnl_history: Dict[str, float] = {}  # date -> pnl
        
        # Pattern learning
        self.patterns: Dict[str, TradePattern] = {}
        self.min_pattern_sample_size = 20
        self.min_win_rate = 40.0  # Avoid patterns with <40% win rate
        
        # Survival targets (configurable)
        self.daily_target_pct = 1.0  # 1% per day target
        self.weekly_target_pct = 5.0  # 5% per week target
        
        # Milestones
        self.milestones_hit = set()
        self.all_time_high = initial_capital
        
        # Load persisted state
        self._load_state()
        
        logger.info(
            "survival_brain_initialized",
            initial_capital=initial_capital,
            current_capital=self.current_capital,
            state=self.current_state.value
        )
    
    def _load_state(self):
        """Load persisted state from disk."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.current_capital = data.get('current_capital', self.initial_capital)
                    self.trade_history = data.get('trade_history', [])
                    self.daily_pnl_history = data.get('daily_pnl_history', {})
                    self.all_time_high = data.get('all_time_high', self.initial_capital)
                    self.milestones_hit = set(data.get('milestones_hit', []))
                    logger.info("survival_state_loaded", capital=self.current_capital)
            
            if self.patterns_file.exists():
                with open(self.patterns_file, 'r') as f:
                    patterns_data = json.load(f)
                    for key, p in patterns_data.items():
                        hour, market_type, edge_bucket = key.split('|')
                        pattern = TradePattern(
                            hour_of_day=int(hour),
                            market_type=market_type,
                            edge_bucket=edge_bucket,
                            wins=p['wins'],
                            losses=p['losses'],
                            total_pnl=p['total_pnl']
                        )
                        self.patterns[key] = pattern
                    logger.info("patterns_loaded", pattern_count=len(self.patterns))
        
        except Exception as e:
            logger.error("failed_to_load_survival_state", error=str(e))
    
    def _save_state(self):
        """Persist state to disk."""
        try:
            state_data = {
                'current_capital': self.current_capital,
                'trade_history': self.trade_history[-1000:],  # Keep last 1000 trades
                'daily_pnl_history': self.daily_pnl_history,
                'all_time_high': self.all_time_high,
                'milestones_hit': list(self.milestones_hit),
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
            
            # Save patterns
            patterns_data = {}
            for key, pattern in self.patterns.items():
                patterns_data[key] = {
                    'wins': pattern.wins,
                    'losses': pattern.losses,
                    'total_pnl': pattern.total_pnl,
                    'win_rate': pattern.win_rate,
                    'sample_size': pattern.sample_size
                }
            
            with open(self.patterns_file, 'w') as f:
                json.dump(patterns_data, f, indent=2)
        
        except Exception as e:
            logger.error("failed_to_save_survival_state", error=str(e))
    
    def _calculate_state(self) -> SurvivalState:
        """Determine current survival state based on capital percentage."""
        capital_pct = (self.current_capital / self.initial_capital) * 100
        
        if capital_pct > 120:
            return SurvivalState.THRIVING
        elif capital_pct >= 80:
            return SurvivalState.HEALTHY
        elif capital_pct >= 50:
            return SurvivalState.WOUNDED
        elif capital_pct >= 20:
            return SurvivalState.CRITICAL
        else:
            return SurvivalState.DEAD
    
    def _get_kelly_modifier(self, state: SurvivalState) -> float:
        """Get position sizing modifier based on state."""
        modifiers = {
            SurvivalState.THRIVING: 1.2,   # Aggressive compounding
            SurvivalState.HEALTHY: 1.0,    # Normal Kelly
            SurvivalState.WOUNDED: 0.5,    # Conservative
            SurvivalState.CRITICAL: 0.25,  # Survival mode
            SurvivalState.DEAD: 0.0        # No trading
        }
        return modifiers[state]
    
    def _get_min_edge_threshold(self, state: SurvivalState, behind_target_pct: float) -> float:
        """
        Get minimum edge threshold based on state and hunger.
        
        Hunger mechanism: If behind target, slightly lower threshold (hunt more),
        but NEVER compromise position sizing.
        """
        base_thresholds = {
            SurvivalState.THRIVING: 1.5,   # Can take lower-edge plays when thriving
            SurvivalState.HEALTHY: 2.0,    # Base threshold
            SurvivalState.WOUNDED: 5.0,    # Only high-edge plays
            SurvivalState.CRITICAL: 10.0,  # Desperation — only huge edges
            SurvivalState.DEAD: 999.0      # Don't trade
        }
        
        base_threshold = base_thresholds[state]
        
        # Hunger adjustment (only when HEALTHY or THRIVING)
        if state in [SurvivalState.HEALTHY, SurvivalState.THRIVING]:
            if behind_target_pct > 50:
                # Very hungry — lower threshold by 20% (but never below 1.0%)
                return max(1.0, base_threshold * 0.8)
            elif behind_target_pct > 20:
                # Moderately hungry — lower threshold by 10%
                return max(1.0, base_threshold * 0.9)
        
        return base_threshold
    
    def _calculate_burn_rate(self) -> Tuple[float, Optional[float]]:
        """
        Calculate daily burn rate and days of runway.
        
        Returns:
            (daily_burn_rate, days_of_runway)
            days_of_runway is None if we're profitable
        """
        # Look at last 7 days of PnL
        now = datetime.now()
        recent_pnl = []
        
        for i in range(7):
            date_key = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            if date_key in self.daily_pnl_history:
                recent_pnl.append(self.daily_pnl_history[date_key])
        
        if not recent_pnl:
            # No history yet — assume break-even
            return 0.0, None
        
        avg_daily_pnl = sum(recent_pnl) / len(recent_pnl)
        
        if avg_daily_pnl >= 0:
            # We're profitable — no runway concern
            return avg_daily_pnl, None
        
        # We're losing money — calculate runway
        daily_burn_rate = abs(avg_daily_pnl)
        
        if daily_burn_rate > 0:
            days_of_runway = self.current_capital / daily_burn_rate
        else:
            days_of_runway = None
        
        return avg_daily_pnl, days_of_runway
    
    def _calculate_recovery_trades_needed(self) -> Tuple[int, float]:
        """
        Calculate how many winning trades needed to get back to HEALTHY (80%).
        
        Returns:
            (trades_needed, avg_win_size)
        """
        healthy_threshold = self.initial_capital * 0.8
        capital_deficit = healthy_threshold - self.current_capital
        
        if capital_deficit <= 0:
            return 0, 0.0
        
        # Calculate average win size from recent winners
        recent_wins = [
            t['pnl'] for t in self.trade_history[-100:]
            if t.get('pnl', 0) > 0
        ]
        
        if not recent_wins:
            # No win history — estimate based on 5% edge with 2% position size
            avg_win = self.current_capital * 0.02 * 0.05
        else:
            avg_win = sum(recent_wins) / len(recent_wins)
        
        trades_needed = int(capital_deficit / avg_win) + 1 if avg_win > 0 else 999
        
        return trades_needed, avg_win
    
    def _calculate_target_metrics(self) -> Dict:
        """Calculate target-related metrics."""
        # Daily target
        daily_target = self.current_capital * (self.daily_target_pct / 100)
        
        # Weekly target
        week_start = datetime.now() - timedelta(days=datetime.now().weekday())
        week_start_str = week_start.strftime('%Y-%m-%d')
        
        weekly_target = self.current_capital * (self.weekly_target_pct / 100)
        
        # Today's PnL
        today_str = datetime.now().strftime('%Y-%m-%d')
        daily_pnl = self.daily_pnl_history.get(today_str, 0.0)
        
        # This week's PnL
        weekly_pnl = 0.0
        for i in range(7):
            date_key = (week_start + timedelta(days=i)).strftime('%Y-%m-%d')
            weekly_pnl += self.daily_pnl_history.get(date_key, 0.0)
        
        # How far behind?
        if daily_pnl < daily_target:
            behind_daily_pct = ((daily_target - daily_pnl) / daily_target * 100) if daily_target > 0 else 0
        else:
            behind_daily_pct = 0.0
        
        if weekly_pnl < weekly_target:
            behind_weekly_pct = ((weekly_target - weekly_pnl) / weekly_target * 100) if weekly_target > 0 else 0
        else:
            behind_weekly_pct = 0.0
        
        # Use the worse of the two
        behind_target_pct = max(behind_daily_pct, behind_weekly_pct)
        
        return {
            'daily_target': daily_target,
            'weekly_target': weekly_target,
            'daily_pnl': daily_pnl,
            'weekly_pnl': weekly_pnl,
            'behind_target_pct': behind_target_pct
        }
    
    def _get_pattern_key(self, hour: int, market_type: str, edge: float) -> str:
        """Generate pattern key for lookup."""
        if edge < 2:
            edge_bucket = "0-2%"
        elif edge < 5:
            edge_bucket = "2-5%"
        elif edge < 10:
            edge_bucket = "5-10%"
        else:
            edge_bucket = "10%+"
        
        return f"{hour}|{market_type}|{edge_bucket}"
    
    def _is_pattern_filtered(self, pattern_key: str) -> bool:
        """Check if a pattern should be filtered (avoided)."""
        if pattern_key not in self.patterns:
            return False  # Unknown pattern — allow it
        
        pattern = self.patterns[pattern_key]
        
        # Only filter if we have enough sample size
        if pattern.sample_size < self.min_pattern_sample_size:
            return False
        
        # Filter if win rate is below threshold
        if pattern.win_rate < self.min_win_rate:
            logger.debug(
                "pattern_filtered",
                pattern=pattern_key,
                win_rate=pattern.win_rate,
                sample_size=pattern.sample_size
            )
            return True
        
        return False
    
    async def _send_telegram_alert(self, message: str, alert_type: str, force: bool = False):
        """Send Telegram alert if alerter is configured."""
        if self.telegram_alerter:
            try:
                await self.telegram_alerter.send_alert(message, alert_type=alert_type, force=force)
            except Exception as e:
                logger.error("telegram_alert_failed", error=str(e), alert_type=alert_type)
    
    async def _check_state_transition(self):
        """Check for state transitions and send alerts."""
        if self.current_state != self.previous_state:
            capital_pct = (self.current_capital / self.initial_capital) * 100
            
            # State transition alert
            message = f"🔄 <b>SURVIVAL STATE CHANGE</b>\n\n"
            message += f"<b>{self.previous_state.value}</b> → <b>{self.current_state.value}</b>\n\n"
            message += f"Capital: ${self.current_capital:.2f} ({capital_pct:.1f}%)\n"
            message += f"Initial: ${self.initial_capital:.2f}"
            
            await self._send_telegram_alert(message, alert_type="state_transition", force=True)
            
            # Special alerts for dangerous states
            if self.current_state == SurvivalState.WOUNDED:
                warning = f"⚠️ <b>WOUNDED STATE</b>\n\n"
                warning += f"Capital dropped to {capital_pct:.1f}%\n"
                warning += f"Switching to conservative mode:\n"
                warning += f"• Only trades with >5% edge\n"
                warning += f"• Position size reduced to 50%\n"
                warning += f"• Focus on capital preservation"
                await self._send_telegram_alert(warning, alert_type="wounded", force=True)
            
            elif self.current_state == SurvivalState.CRITICAL:
                warning = f"🚨 <b>CRITICAL STATE</b>\n\n"
                warning += f"Capital at {capital_pct:.1f}% — DESPERATION MODE\n\n"
                warning += f"Survival protocols:\n"
                warning += f"• Only trades with >10% edge\n"
                warning += f"• Position size reduced to 25%\n"
                warning += f"• Fighting for survival"
                await self._send_telegram_alert(warning, alert_type="critical", force=True)
            
            elif self.current_state == SurvivalState.DEAD:
                warning = f"☠️ <b>DEAD STATE</b>\n\n"
                warning += f"Capital at {capital_pct:.1f}% — TRADING HALTED\n\n"
                warning += f"Remaining: ${self.current_capital:.2f}\n"
                warning += f"Lost: ${self.initial_capital - self.current_capital:.2f}\n\n"
                warning += f"@basel — Need guidance."
                await self._send_telegram_alert(warning, alert_type="dead", force=True)
            
            self.previous_state = self.current_state
    
    async def _check_milestones(self):
        """Check for survival milestones and celebrate."""
        capital_pct = (self.current_capital / self.initial_capital) * 100
        
        # First profitable day
        today_str = datetime.now().strftime('%Y-%m-%d')
        today_pnl = self.daily_pnl_history.get(today_str, 0.0)
        
        if today_pnl > 0 and "first_profitable_day" not in self.milestones_hit:
            self.milestones_hit.add("first_profitable_day")
            message = f"🎉 <b>FIRST PROFITABLE DAY</b>\n\n"
            message += f"+${today_pnl:.2f} today\n"
            message += f"Capital: ${self.current_capital:.2f}"
            await self._send_telegram_alert(message, alert_type="milestone", force=True)
        
        # New all-time high
        if self.current_capital > self.all_time_high:
            old_ath = self.all_time_high
            self.all_time_high = self.current_capital
            
            message = f"🚀 <b>NEW ALL-TIME HIGH</b>\n\n"
            message += f"${self.current_capital:.2f} ({capital_pct:.1f}%)\n"
            message += f"Previous ATH: ${old_ath:.2f}\n"
            message += f"Gain: +${self.current_capital - old_ath:.2f}"
            await self._send_telegram_alert(message, alert_type="milestone", force=True)
        
        # 2x milestone
        if capital_pct >= 200 and "2x_capital" not in self.milestones_hit:
            self.milestones_hit.add("2x_capital")
            message = f"💎 <b>2X CAPITAL ACHIEVED</b>\n\n"
            message += f"${self.current_capital:.2f} (200%)\n"
            message += f"We're thriving. Keep compounding."
            await self._send_telegram_alert(message, alert_type="milestone", force=True)
    
    async def _check_hunger_alerts(self, behind_target_pct: float):
        """Send alerts when we're far behind target."""
        if behind_target_pct > 50:
            # Very hungry — need Basel's guidance
            message = f"🍽️ <b>HUNGER ALERT</b>\n\n"
            message += f"Behind target by {behind_target_pct:.1f}%\n\n"
            message += f"Edge threshold lowered to hunt more opportunities.\n"
            message += f"Position sizing unchanged (safety first).\n\n"
            message += f"@basel — Need guidance if this continues."
            await self._send_telegram_alert(message, alert_type="hunger", force=False)
        
        elif behind_target_pct > 20:
            # Moderately hungry
            message = f"📉 Behind target by {behind_target_pct:.1f}%\n"
            message += f"Lowering edge threshold slightly to hunt more."
            await self._send_telegram_alert(message, alert_type="hunger", force=False)
    
    def get_position_size_modifier(self) -> float:
        """
        Get position sizing modifier for execution engine.
        
        Called by execution engine to adjust Kelly sizing based on survival state.
        
        Returns:
            Kelly multiplier (0.0 to 1.2)
        """
        return self._get_kelly_modifier(self.current_state)
    
    def should_take_trade(
        self,
        edge: float,
        market_type: str,
        hour: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Determine if a trade should be taken based on survival state and patterns.
        
        Called by edge detector before placing a trade.
        
        Args:
            edge: Expected edge percentage (e.g., 5.0 for 5%)
            market_type: Type of market (e.g., "btc_price", "binary_event")
            hour: Hour of day (0-23), defaults to current hour
        
        Returns:
            (should_take, reason)
        """
        if hour is None:
            hour = datetime.now().hour
        
        # Get current metrics
        metrics = self.get_survival_status()
        
        # Check if we're dead
        if self.current_state == SurvivalState.DEAD:
            return False, "DEAD state — trading halted"
        
        # Check edge threshold
        if edge < metrics.min_edge_threshold:
            return False, f"Edge {edge:.2f}% below threshold {metrics.min_edge_threshold:.2f}%"
        
        # Check pattern filtering (only if we have enough data)
        pattern_key = self._get_pattern_key(hour, market_type, edge)
        if self._is_pattern_filtered(pattern_key):
            pattern = self.patterns[pattern_key]
            return False, f"Pattern filtered — {pattern.win_rate:.1f}% win rate over {pattern.sample_size} trades"
        
        # All checks passed
        return True, "Trade approved"
    
    def record_trade_result(self, trade_data: Dict):
        """
        Record trade result and update survival metrics.
        
        Called after trade resolution.
        
        Args:
            trade_data: Dict with keys:
                - pnl: float (profit/loss)
                - edge: float (expected edge)
                - market_type: str
                - timestamp: datetime or ISO string
                - won: bool
        """
        # Add to trade history
        if isinstance(trade_data.get('timestamp'), datetime):
            trade_data['timestamp'] = trade_data['timestamp'].isoformat()
        
        self.trade_history.append(trade_data)
        
        # Update capital
        pnl = trade_data.get('pnl', 0.0)
        self.current_capital += pnl
        
        # Update daily PnL
        if 'timestamp' in trade_data:
            date_str = trade_data['timestamp'][:10]  # YYYY-MM-DD
        else:
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        if date_str not in self.daily_pnl_history:
            self.daily_pnl_history[date_str] = 0.0
        self.daily_pnl_history[date_str] += pnl
        
        # Update pattern learning
        timestamp = datetime.fromisoformat(trade_data['timestamp']) if 'timestamp' in trade_data else datetime.now()
        hour = timestamp.hour
        market_type = trade_data.get('market_type', 'unknown')
        edge = trade_data.get('edge', 0.0)
        won = trade_data.get('won', False)
        
        pattern_key = self._get_pattern_key(hour, market_type, edge)
        
        if pattern_key not in self.patterns:
            self.patterns[pattern_key] = TradePattern(
                hour_of_day=hour,
                market_type=market_type,
                edge_bucket=pattern_key.split('|')[2]
            )
        
        pattern = self.patterns[pattern_key]
        if won:
            pattern.wins += 1
        else:
            pattern.losses += 1
        pattern.total_pnl += pnl
        
        # Update state
        self.current_state = self._calculate_state()
        
        # Save state
        self._save_state()
        
        logger.info(
            "trade_recorded",
            pnl=pnl,
            capital=self.current_capital,
            state=self.current_state.value,
            pattern=pattern_key,
            pattern_win_rate=pattern.win_rate
        )
    
    def get_survival_status(self) -> SurvivalMetrics:
        """
        Get current survival status for dashboard.
        
        Returns complete survival metrics including state, runway, targets, etc.
        """
        # Calculate all metrics
        capital_pct = (self.current_capital / self.initial_capital) * 100
        daily_burn_rate, days_of_runway = self._calculate_burn_rate()
        recovery_trades_needed, avg_win_size = self._calculate_recovery_trades_needed()
        target_metrics = self._calculate_target_metrics()
        
        # State and modifiers
        state = self._calculate_state()
        kelly_modifier = self._get_kelly_modifier(state)
        min_edge_threshold = self._get_min_edge_threshold(state, target_metrics['behind_target_pct'])
        
        # Pattern stats
        total_patterns = len(self.patterns)
        filtered_patterns = sum(1 for key in self.patterns if self._is_pattern_filtered(key))
        
        return SurvivalMetrics(
            current_capital=self.current_capital,
            initial_capital=self.initial_capital,
            capital_pct=capital_pct,
            state=state,
            daily_burn_rate=daily_burn_rate,
            days_of_runway=days_of_runway,
            recovery_trades_needed=recovery_trades_needed,
            avg_win_size=avg_win_size,
            daily_target=target_metrics['daily_target'],
            weekly_target=target_metrics['weekly_target'],
            daily_pnl=target_metrics['daily_pnl'],
            weekly_pnl=target_metrics['weekly_pnl'],
            behind_target_pct=target_metrics['behind_target_pct'],
            kelly_modifier=kelly_modifier,
            min_edge_threshold=min_edge_threshold,
            total_patterns=total_patterns,
            filtered_patterns=filtered_patterns
        )
    
    async def send_daily_survival_report(self):
        """
        Send end-of-day survival report to Telegram.
        
        Should be called once per day (e.g., at 23:59).
        """
        metrics = self.get_survival_status()
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        today_pnl = self.daily_pnl_history.get(today_str, 0.0)
        
        # Build report
        report = f"📊 <b>DAILY SURVIVAL REPORT</b>\n"
        report += f"{datetime.now().strftime('%Y-%m-%d')}\n\n"
        
        # State indicator
        state_emoji = {
            SurvivalState.THRIVING: "🚀",
            SurvivalState.HEALTHY: "✅",
            SurvivalState.WOUNDED: "⚠️",
            SurvivalState.CRITICAL: "🚨",
            SurvivalState.DEAD: "☠️"
        }
        report += f"{state_emoji[metrics.state]} <b>State:</b> {metrics.state.value}\n\n"
        
        # Capital
        report += f"💰 <b>Capital:</b> ${metrics.current_capital:.2f} ({metrics.capital_pct:.1f}%)\n"
        report += f"📈 <b>Today's PnL:</b> {'+ ' if today_pnl >= 0 else ''} ${today_pnl:.2f}\n"
        report += f"🎯 <b>Daily Target:</b> ${metrics.daily_target:.2f}\n\n"
        
        # Runway (if losing)
        if metrics.days_of_runway:
            report += f"⏳ <b>Runway:</b> {metrics.days_of_runway:.1f} days\n"
            report += f"🔧 <b>Recovery Trades Needed:</b> {metrics.recovery_trades_needed}\n\n"
        
        # Position sizing
        report += f"📊 <b>Kelly Modifier:</b> {metrics.kelly_modifier:.2f}x\n"
        report += f"🎲 <b>Min Edge:</b> {metrics.min_edge_threshold:.1f}%\n\n"
        
        # Pattern learning
        report += f"🧠 <b>Patterns:</b> {metrics.total_patterns} total, {metrics.filtered_patterns} filtered\n"
        
        # Behind target?
        if metrics.behind_target_pct > 0:
            report += f"\n📉 <b>Behind target:</b> {metrics.behind_target_pct:.1f}%"
        
        await self._send_telegram_alert(report, alert_type="daily_report", force=True)
    
    async def tick(self):
        """
        Regular tick for background tasks (state transitions, alerts, etc.).
        
        Call this periodically (e.g., every 5 minutes) from main loop.
        """
        # Update state
        self.current_state = self._calculate_state()
        
        # Check for state transitions
        await self._check_state_transition()
        
        # Check for milestones
        await self._check_milestones()
        
        # Check hunger
        metrics = self.get_survival_status()
        await self._check_hunger_alerts(metrics.behind_target_pct)
        
        # Save state periodically
        self._save_state()
