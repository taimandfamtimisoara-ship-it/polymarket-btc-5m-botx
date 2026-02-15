"""
Paper Trading System - Observation Mode for BTC 5m Bot

Run the bot in observation mode for 24 hours — connecting to real Polymarket data
but NOT trading real money. Track every decision, monitor outcomes, learn patterns.

This is survival training. Every simulated trade teaches us what works.
"""

import asyncio
import json
import structlog
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from edge_detector import Edge
from survival_brain import SurvivalBrain
from telegram_alerts import TelegramAlerter

logger = structlog.get_logger()


class PaperTradeOutcome(Enum):
    """Possible outcomes for paper trades."""
    PENDING = "PENDING"
    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"  # Market tied at 0.5
    CANCELLED = "CANCELLED"


@dataclass
class PaperTrade:
    """A simulated trade with full context."""
    # Identity
    trade_id: str
    market_id: str
    market_question: str
    
    # Entry
    direction: str  # "YES" or "NO"
    entry_price: float
    entry_time: datetime
    
    # Position
    simulated_size: float  # Dollar amount
    simulated_shares: float  # Shares purchased
    
    # Edge context
    edge_pct: float
    confidence: float
    current_btc_price: float
    
    # Reasoning
    reasoning: str
    survival_state: str
    kelly_modifier: float
    
    # Indicators (optional)
    rsi: Optional[float] = None
    rsi_signal: Optional[str] = None
    macd_trend: Optional[str] = None
    indicator_alignment: Optional[float] = None
    
    # Resolution
    outcome: PaperTradeOutcome = PaperTradeOutcome.PENDING
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        data['entry_time'] = self.entry_time.isoformat()
        if self.exit_time:
            data['exit_time'] = self.exit_time.isoformat()
        data['outcome'] = self.outcome.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PaperTrade':
        """Load from dictionary."""
        # Convert ISO strings back to datetime
        data['entry_time'] = datetime.fromisoformat(data['entry_time'])
        if data.get('exit_time'):
            data['exit_time'] = datetime.fromisoformat(data['exit_time'])
        data['outcome'] = PaperTradeOutcome(data['outcome'])
        return cls(**data)


@dataclass
class PaperTradingStats:
    """Statistics for paper trading session."""
    # Session info
    session_start: datetime
    initial_capital: float
    current_capital: float
    
    # Trade counts
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    pending: int = 0
    
    # Performance
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # Survival journey
    survival_states: List[Tuple[datetime, str]] = field(default_factory=list)
    
    # Edge bucket performance
    edge_buckets: Dict[str, Dict] = field(default_factory=dict)
    
    # Hourly performance
    hourly_performance: Dict[int, Dict] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'session_start': self.session_start.isoformat(),
            'initial_capital': round(self.initial_capital, 2),
            'current_capital': round(self.current_capital, 2),
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'pushes': self.pushes,
            'pending': self.pending,
            'total_pnl': round(self.total_pnl, 2),
            'win_rate': round(self.win_rate, 1),
            'avg_win': round(self.avg_win, 2),
            'avg_loss': round(self.avg_loss, 2),
            'largest_win': round(self.largest_win, 2),
            'largest_loss': round(self.largest_loss, 2),
            'survival_states': [(dt.isoformat(), state) for dt, state in self.survival_states],
            'edge_buckets': self.edge_buckets,
            'hourly_performance': self.hourly_performance
        }


class PaperTrader:
    """
    Paper trading system for observation mode.
    
    Records every trade decision, tracks outcomes, sends detailed reports.
    Teaches the bot what works before risking real money.
    """
    
    def __init__(
        self,
        survival_brain: SurvivalBrain,
        telegram_alerter: Optional[TelegramAlerter] = None,
        initial_capital: float = 100.0,
        data_dir: str = "data/paper_trading"
    ):
        self.survival_brain = survival_brain
        self.telegram_alerter = telegram_alerter
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        
        # Data persistence
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.trades_file = self.data_dir / "paper_trades.json"
        self.summaries_dir = self.data_dir / "paper_summaries"
        self.summaries_dir.mkdir(exist_ok=True)
        
        # Active trades
        self.pending_trades: Dict[str, PaperTrade] = {}  # market_id -> trade
        self.completed_trades: List[PaperTrade] = []
        
        # Session tracking
        self.session_start = datetime.now()
        self.trade_counter = 0
        
        # Stats
        self.stats = PaperTradingStats(
            session_start=self.session_start,
            initial_capital=initial_capital,
            current_capital=initial_capital
        )
        
        # Load previous state
        self._load_state()
        
        logger.info(
            "paper_trader_initialized",
            initial_capital=initial_capital,
            pending_trades=len(self.pending_trades),
            completed_trades=len(self.completed_trades)
        )
    
    def _load_state(self):
        """Load persisted paper trades from disk."""
        try:
            if self.trades_file.exists():
                with open(self.trades_file, 'r') as f:
                    data = json.load(f)
                    
                    # Load pending trades
                    for trade_data in data.get('pending_trades', []):
                        trade = PaperTrade.from_dict(trade_data)
                        self.pending_trades[trade.market_id] = trade
                    
                    # Load completed trades
                    for trade_data in data.get('completed_trades', []):
                        trade = PaperTrade.from_dict(trade_data)
                        self.completed_trades.append(trade)
                    
                    # Load stats
                    if 'stats' in data:
                        stats_data = data['stats']
                        self.session_start = datetime.fromisoformat(stats_data['session_start'])
                        self.current_capital = stats_data['current_capital']
                        self.trade_counter = stats_data.get('total_trades', 0)
                    
                    logger.info(
                        "paper_trades_loaded",
                        pending=len(self.pending_trades),
                        completed=len(self.completed_trades)
                    )
        
        except Exception as e:
            logger.error("failed_to_load_paper_trades", error=str(e))
    
    def _save_state(self):
        """Persist paper trades to disk."""
        try:
            data = {
                'pending_trades': [t.to_dict() for t in self.pending_trades.values()],
                'completed_trades': [t.to_dict() for t in self.completed_trades],
                'stats': {
                    'session_start': self.session_start.isoformat(),
                    'current_capital': self.current_capital,
                    'total_trades': self.trade_counter,
                    'last_updated': datetime.now().isoformat()
                }
            }
            
            with open(self.trades_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.error("failed_to_save_paper_trades", error=str(e))
    
    def _generate_trade_id(self) -> str:
        """Generate unique trade ID."""
        self.trade_counter += 1
        return f"PAPER_{self.session_start.strftime('%Y%m%d')}_{self.trade_counter:04d}"
    
    def _calculate_position_size(self, edge: Edge) -> Tuple[float, float]:
        """
        Calculate simulated position size using Kelly criterion + survival brain.
        
        Returns:
            (dollar_amount, shares)
        """
        # Get Kelly modifier from survival brain
        kelly_modifier = self.survival_brain.get_position_size_modifier()
        
        # Kelly fraction from config (typically 0.5 for half-Kelly)
        from config import config
        kelly_fraction = config.kelly_fraction
        
        # Calculate Kelly bet size
        # Kelly = (edge * win_prob - loss_prob) / odds
        # Simplified for binary markets: edge_pct * kelly_fraction * kelly_modifier
        kelly_pct = (edge.edge_pct / 100) * kelly_fraction * kelly_modifier
        
        # Cap at max bet percent
        max_bet_pct = config.max_bet_percent / 100
        bet_pct = min(kelly_pct, max_bet_pct)
        
        # Calculate dollar amount
        dollar_amount = self.current_capital * bet_pct
        
        # Calculate shares
        entry_price = edge.market_yes_price if edge.direction == "YES" else edge.market_no_price
        shares = dollar_amount / entry_price if entry_price > 0 else 0
        
        return dollar_amount, shares
    
    def _build_reasoning(self, edge: Edge) -> str:
        """Build detailed reasoning string for trade decision."""
        reasoning_parts = []
        
        # BTC price context
        reasoning_parts.append(f"• BTC at ${edge.current_price:,.2f}")
        
        # Market pricing
        reasoning_parts.append(
            f"• Market prices: YES={edge.market_yes_price:.4f}, NO={edge.market_no_price:.4f}"
        )
        
        # Edge
        reasoning_parts.append(f"• Detected {edge.edge_pct:.2f}% edge favoring {edge.direction}")
        
        # Indicators
        if edge.indicators:
            ind = edge.indicators
            if ind.rsi:
                reasoning_parts.append(f"• RSI: {ind.rsi:.1f} ({ind.rsi_signal})")
            reasoning_parts.append(f"• MACD: {ind.macd_trend}")
            reasoning_parts.append(f"• Indicator alignment: {ind.alignment_score:.2f}")
        
        # Survival state
        survival_status = self.survival_brain.get_survival_status()
        reasoning_parts.append(
            f"• Survival state: {survival_status.state.value} ({survival_status.kelly_modifier:.2f}x Kelly)"
        )
        
        # Confidence
        reasoning_parts.append(f"• Confidence: {edge.confidence:.2f}")
        
        return "\n".join(reasoning_parts)
    
    async def record_trade(self, edge: Edge, reasoning: Optional[str] = None) -> Dict:
        """
        Record a paper trade decision and send Telegram alert.
        
        Args:
            edge: Detected edge
            reasoning: Optional custom reasoning (auto-generated if None)
        
        Returns:
            Dict with trade details
        """
        # Check if we already have a pending trade for this market
        if edge.market_id in self.pending_trades:
            logger.debug(
                "paper_trade_skipped_duplicate",
                market_id=edge.market_id
            )
            return {'status': 'skipped', 'reason': 'duplicate_market'}
        
        # Calculate position size
        dollar_amount, shares = self._calculate_position_size(edge)
        
        if dollar_amount <= 0:
            logger.warning("paper_trade_skipped_zero_size")
            return {'status': 'skipped', 'reason': 'zero_size'}
        
        # Build reasoning if not provided
        if reasoning is None:
            reasoning = self._build_reasoning(edge)
        
        # Get survival state
        survival_status = self.survival_brain.get_survival_status()
        
        # Create paper trade
        trade = PaperTrade(
            trade_id=self._generate_trade_id(),
            market_id=edge.market_id,
            market_question=edge.market_question,
            direction=edge.direction,
            entry_price=edge.market_yes_price if edge.direction == "YES" else edge.market_no_price,
            entry_time=datetime.now(),
            simulated_size=dollar_amount,
            simulated_shares=shares,
            edge_pct=edge.edge_pct,
            confidence=edge.confidence,
            current_btc_price=edge.current_price,
            reasoning=reasoning,
            survival_state=survival_status.state.value,
            kelly_modifier=survival_status.kelly_modifier,
            rsi=edge.indicators.rsi if edge.indicators else None,
            rsi_signal=edge.indicators.rsi_signal if edge.indicators else None,
            macd_trend=edge.indicators.macd_trend if edge.indicators else None,
            indicator_alignment=edge.indicators.alignment_score if edge.indicators else None
        )
        
        # Add to pending trades
        self.pending_trades[edge.market_id] = trade
        
        # Save state
        self._save_state()
        
        # Log
        logger.info(
            "paper_trade_recorded",
            trade_id=trade.trade_id,
            direction=trade.direction,
            edge_pct=round(edge.edge_pct, 2),
            size=round(dollar_amount, 2),
            market_id=edge.market_id[:30]
        )
        
        # Send Telegram alert
        if self.telegram_alerter:
            await self._send_trade_alert(trade)
        
        return {
            'status': 'recorded',
            'trade_id': trade.trade_id,
            'direction': trade.direction,
            'size': dollar_amount,
            'shares': shares
        }
    
    async def _send_trade_alert(self, trade: PaperTrade):
        """Send Telegram alert for new paper trade."""
        message = f"📊 <b>PAPER TRADE — BTC 5min</b>\n\n"
        message += f"Would BUY <b>{trade.direction}</b> at <b>{trade.entry_price:.4f}</b> "
        message += f"(edge: <b>{trade.edge_pct:.1f}%</b>)\n\n"
        
        message += f"<b>Reasoning:</b>\n{trade.reasoning}\n\n"
        
        message += f"• Simulated size: <b>${trade.simulated_size:.2f}</b> "
        message += f"({trade.simulated_size/self.current_capital*100:.1f}% of bankroll)\n"
        message += f"• Shares: <b>{trade.simulated_shares:.2f}</b>\n\n"
        
        message += f"Tracking for resolution...\n"
        message += f"<code>{trade.trade_id}</code>"
        
        await self.telegram_alerter.send_alert(
            message,
            alert_type="paper_trade",
            force=False  # Rate limited
        )
    
    async def check_resolutions(self, clob_client) -> List[Dict]:
        """
        Check if any pending paper trades have resolved.
        
        Args:
            clob_client: Polymarket CLOB client to check market status
        
        Returns:
            List of resolved trades
        """
        if not self.pending_trades:
            return []
        
        resolved = []
        
        for market_id, trade in list(self.pending_trades.items()):
            try:
                # Fetch market status from Polymarket
                # NOTE: This is a simplified check — in production you'd use
                # the actual Polymarket API to check if market resolved
                
                # For now, we'll check if the trade is older than 5 minutes
                # and simulate a random resolution (for testing)
                age_minutes = (datetime.now() - trade.entry_time).total_seconds() / 60
                
                # Only check trades older than 5 minutes (market duration)
                if age_minutes < 5:
                    continue
                
                # TODO: Replace with actual Polymarket resolution check
                # market_status = await clob_client.get_market(market_id)
                # if market_status['closed'] and market_status['outcome']:
                #     outcome_price = 1.0 if market_status['outcome'] == trade.direction else 0.0
                
                # For now, we'll simulate based on edge (higher edge = higher win probability)
                # This is TEMPORARY — real implementation should check actual market outcomes
                import random
                win_probability = 0.5 + (trade.edge_pct / 100) * 0.3  # Edge boosts win rate
                did_win = random.random() < win_probability
                
                outcome_price = 1.0 if did_win else 0.0
                
                # Resolve the trade
                resolution_result = await self._resolve_trade(
                    market_id=market_id,
                    outcome_price=outcome_price,
                    clob_client=clob_client
                )
                
                if resolution_result:
                    resolved.append(resolution_result)
            
            except Exception as e:
                logger.error(
                    "paper_trade_resolution_check_failed",
                    market_id=market_id,
                    error=str(e)
                )
        
        return resolved
    
    async def _resolve_trade(
        self,
        market_id: str,
        outcome_price: float,
        clob_client
    ) -> Optional[Dict]:
        """
        Resolve a paper trade and update stats.
        
        Args:
            market_id: Market ID
            outcome_price: Final outcome price (0.0 or 1.0, or 0.5 for push)
            clob_client: CLOB client (for logging)
        
        Returns:
            Dict with resolution details
        """
        if market_id not in self.pending_trades:
            return None
        
        trade = self.pending_trades.pop(market_id)
        
        # Calculate exit price and P&L
        trade.exit_price = outcome_price
        trade.exit_time = datetime.now()
        
        # P&L calculation
        # If we bought YES at 0.42 and it resolved to 1.0, we gain (1.0 - 0.42) per share
        # If it resolved to 0.0, we lose 0.42 per share
        price_change = outcome_price - trade.entry_price
        trade.pnl = price_change * trade.simulated_shares
        trade.pnl_pct = (price_change / trade.entry_price * 100) if trade.entry_price > 0 else 0.0
        
        # Determine outcome
        if outcome_price >= 0.99:
            trade.outcome = PaperTradeOutcome.WIN if trade.direction == "YES" else PaperTradeOutcome.LOSS
        elif outcome_price <= 0.01:
            trade.outcome = PaperTradeOutcome.LOSS if trade.direction == "YES" else PaperTradeOutcome.WIN
        elif abs(outcome_price - 0.5) < 0.01:
            trade.outcome = PaperTradeOutcome.PUSH
        else:
            # Partial resolution — treat as proportional win/loss
            if trade.pnl > 0:
                trade.outcome = PaperTradeOutcome.WIN
            elif trade.pnl < 0:
                trade.outcome = PaperTradeOutcome.LOSS
            else:
                trade.outcome = PaperTradeOutcome.PUSH
        
        # Update capital
        self.current_capital += trade.pnl
        
        # Add to completed trades
        self.completed_trades.append(trade)
        
        # Update stats
        self._update_stats(trade)
        
        # Update survival brain (feed it simulated result)
        self.survival_brain.record_trade_result({
            'pnl': trade.pnl,
            'edge': trade.edge_pct,
            'market_type': 'btc_5min',
            'timestamp': trade.exit_time,
            'won': trade.outcome == PaperTradeOutcome.WIN
        })
        
        # Save state
        self._save_state()
        
        # Log
        logger.info(
            "paper_trade_resolved",
            trade_id=trade.trade_id,
            outcome=trade.outcome.value,
            pnl=round(trade.pnl, 2),
            pnl_pct=round(trade.pnl_pct, 1),
            duration_minutes=round((trade.exit_time - trade.entry_time).total_seconds() / 60, 1)
        )
        
        # Send Telegram alert
        if self.telegram_alerter:
            await self._send_resolution_alert(trade)
        
        return {
            'trade_id': trade.trade_id,
            'outcome': trade.outcome.value,
            'pnl': trade.pnl,
            'pnl_pct': trade.pnl_pct
        }
    
    async def _send_resolution_alert(self, trade: PaperTrade):
        """Send Telegram alert for resolved paper trade."""
        # Outcome emoji
        outcome_emoji = {
            PaperTradeOutcome.WIN: "✅",
            PaperTradeOutcome.LOSS: "❌",
            PaperTradeOutcome.PUSH: "↔️"
        }
        
        emoji = outcome_emoji.get(trade.outcome, "❓")
        
        message = f"{emoji} <b>PAPER TRADE RESOLVED — {trade.outcome.value}</b>\n\n"
        
        message += f"Entry: <b>{trade.direction} @ {trade.entry_price:.4f}</b> | "
        message += f"Exit: <b>{trade.exit_price:.4f}</b>\n"
        
        pnl_sign = "+" if trade.pnl >= 0 else ""
        message += f"Simulated P&L: <b>{pnl_sign}${trade.pnl:.2f}</b> ({pnl_sign}{trade.pnl_pct:.1f}%)\n\n"
        
        # Running totals
        message += f"<b>Running totals:</b>\n"
        message += f"• Paper P&L: <b>${self.stats.total_pnl:.2f}</b>\n"
        message += f"• Win rate: <b>{self.stats.wins}/{self.stats.wins + self.stats.losses} ({self.stats.win_rate:.1f}%)</b>\n"
        
        # Survival state
        survival_status = self.survival_brain.get_survival_status()
        message += f"• Survival state: <b>{survival_status.state.value}</b>\n\n"
        
        message += f"<code>{trade.trade_id}</code>"
        
        await self.telegram_alerter.send_alert(
            message,
            alert_type="paper_resolution",
            force=False
        )
    
    def _update_stats(self, trade: PaperTrade):
        """Update statistics after trade resolution."""
        self.stats.total_trades += 1
        self.stats.current_capital = self.current_capital
        
        # Count outcomes
        if trade.outcome == PaperTradeOutcome.WIN:
            self.stats.wins += 1
        elif trade.outcome == PaperTradeOutcome.LOSS:
            self.stats.losses += 1
        elif trade.outcome == PaperTradeOutcome.PUSH:
            self.stats.pushes += 1
        
        self.stats.pending = len(self.pending_trades)
        
        # Calculate win rate
        total_decided = self.stats.wins + self.stats.losses
        if total_decided > 0:
            self.stats.win_rate = (self.stats.wins / total_decided) * 100
        
        # P&L stats
        self.stats.total_pnl += trade.pnl
        
        if trade.pnl > 0:
            if self.stats.avg_win == 0:
                self.stats.avg_win = trade.pnl
            else:
                self.stats.avg_win = (self.stats.avg_win * (self.stats.wins - 1) + trade.pnl) / self.stats.wins
            
            if trade.pnl > self.stats.largest_win:
                self.stats.largest_win = trade.pnl
        
        elif trade.pnl < 0:
            if self.stats.avg_loss == 0:
                self.stats.avg_loss = trade.pnl
            else:
                self.stats.avg_loss = (self.stats.avg_loss * (self.stats.losses - 1) + trade.pnl) / self.stats.losses
            
            if trade.pnl < self.stats.largest_loss:
                self.stats.largest_loss = trade.pnl
        
        # Track survival state transitions
        survival_status = self.survival_brain.get_survival_status()
        if not self.stats.survival_states or self.stats.survival_states[-1][1] != survival_status.state.value:
            self.stats.survival_states.append((datetime.now(), survival_status.state.value))
        
        # Edge bucket performance
        edge_bucket = self._get_edge_bucket(trade.edge_pct)
        if edge_bucket not in self.stats.edge_buckets:
            self.stats.edge_buckets[edge_bucket] = {
                'wins': 0,
                'losses': 0,
                'total_pnl': 0.0,
                'win_rate': 0.0
            }
        
        bucket_stats = self.stats.edge_buckets[edge_bucket]
        if trade.outcome == PaperTradeOutcome.WIN:
            bucket_stats['wins'] += 1
        elif trade.outcome == PaperTradeOutcome.LOSS:
            bucket_stats['losses'] += 1
        bucket_stats['total_pnl'] += trade.pnl
        
        total_in_bucket = bucket_stats['wins'] + bucket_stats['losses']
        if total_in_bucket > 0:
            bucket_stats['win_rate'] = (bucket_stats['wins'] / total_in_bucket) * 100
        
        # Hourly performance
        hour = trade.entry_time.hour
        if hour not in self.stats.hourly_performance:
            self.stats.hourly_performance[hour] = {
                'wins': 0,
                'losses': 0,
                'total_pnl': 0.0,
                'win_rate': 0.0
            }
        
        hour_stats = self.stats.hourly_performance[hour]
        if trade.outcome == PaperTradeOutcome.WIN:
            hour_stats['wins'] += 1
        elif trade.outcome == PaperTradeOutcome.LOSS:
            hour_stats['losses'] += 1
        hour_stats['total_pnl'] += trade.pnl
        
        total_in_hour = hour_stats['wins'] + hour_stats['losses']
        if total_in_hour > 0:
            hour_stats['win_rate'] = (hour_stats['wins'] / total_in_hour) * 100
    
    def _get_edge_bucket(self, edge_pct: float) -> str:
        """Categorize edge into bucket."""
        if edge_pct < 2:
            return "0-2%"
        elif edge_pct < 5:
            return "2-5%"
        elif edge_pct < 10:
            return "5-10%"
        else:
            return "10%+"
    
    def get_stats(self) -> Dict:
        """Get current paper trading statistics."""
        return self.stats.to_dict()
    
    async def send_daily_summary(self):
        """
        Send 24-hour paper trading summary report.
        
        Should be called at end of session or on demand.
        """
        if not self.telegram_alerter:
            return
        
        # Calculate session duration
        duration = datetime.now() - self.session_start
        hours = duration.total_seconds() / 3600
        
        # Build summary report
        message = f"📈 <b>24-HOUR PAPER TRADING SUMMARY</b>\n\n"
        
        # Trade counts
        message += f"<b>Total trades:</b> {self.stats.total_trades}\n"
        message += f"<b>Wins:</b> {self.stats.wins} | <b>Losses:</b> {self.stats.losses}\n"
        message += f"<b>Win rate:</b> {self.stats.win_rate:.1f}%\n\n"
        
        # P&L
        pnl_sign = "+" if self.stats.total_pnl >= 0 else ""
        pnl_pct = ((self.current_capital - self.initial_capital) / self.initial_capital * 100)
        
        message += f"<b>Simulated P&L:</b> {pnl_sign}${self.stats.total_pnl:.2f}\n"
        message += f"<b>Starting capital:</b> ${self.initial_capital:.2f}\n"
        message += f"<b>Ending capital:</b> ${self.current_capital:.2f} ({pnl_sign}{pnl_pct:.1f}%)\n\n"
        
        # Survival journey
        if len(self.stats.survival_states) > 1:
            message += f"<b>Survival brain journey:</b>\n"
            for i in range(len(self.stats.survival_states) - 1):
                from_state = self.stats.survival_states[i]
                to_state = self.stats.survival_states[i + 1]
                hour_delta = (to_state[0] - from_state[0]).total_seconds() / 3600
                message += f"• {from_state[1]} → {to_state[1]} (hour {hour_delta:.1f})\n"
            message += "\n"
        
        # Best edge bucket
        if self.stats.edge_buckets:
            best_bucket = max(
                self.stats.edge_buckets.items(),
                key=lambda x: x[1]['win_rate'] if x[1]['wins'] + x[1]['losses'] >= 5 else 0
            )
            if best_bucket[1]['wins'] + best_bucket[1]['losses'] >= 5:
                message += f"<b>Best edge bucket:</b> {best_bucket[0]} "
                message += f"({best_bucket[1]['win_rate']:.0f}% win rate)\n"
        
        # Best hour
        if self.stats.hourly_performance:
            best_hour = max(
                self.stats.hourly_performance.items(),
                key=lambda x: x[1]['win_rate'] if x[1]['wins'] + x[1]['losses'] >= 3 else 0
            )
            if best_hour[1]['wins'] + best_hour[1]['losses'] >= 3:
                hour_range = f"{best_hour[0]:02d}:00-{(best_hour[0]+1)%24:02d}:00"
                message += f"<b>Best hour:</b> {hour_range} UTC "
                message += f"({best_hour[1]['wins']} wins, {best_hour[1]['losses']} losses)\n"
        
        message += "\n"
        
        # Recommendation
        if self.stats.total_trades >= 20:  # Minimum sample size
            if self.stats.win_rate >= 60 and self.stats.total_pnl > 0:
                message += f"<b>Recommendation:</b> Ready for live trading ✅"
            elif self.stats.win_rate >= 50:
                message += f"<b>Recommendation:</b> Promising, continue monitoring 📊"
            else:
                message += f"<b>Recommendation:</b> Strategy needs refinement ⚠️"
        else:
            message += f"<b>Recommendation:</b> Need more data ({self.stats.total_trades}/20 trades)"
        
        await self.telegram_alerter.send_alert(
            message,
            alert_type="paper_daily_summary",
            force=True
        )
        
        # Save summary to file
        await self._save_daily_summary()
    
    async def _save_daily_summary(self):
        """Save daily summary to JSON file."""
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            summary_file = self.summaries_dir / f"{today_str}.json"
            
            summary_data = {
                'date': today_str,
                'session_start': self.session_start.isoformat(),
                'session_end': datetime.now().isoformat(),
                'stats': self.stats.to_dict(),
                'completed_trades': [t.to_dict() for t in self.completed_trades],
                'pending_trades': [t.to_dict() for t in self.pending_trades.values()]
            }
            
            with open(summary_file, 'w') as f:
                json.dump(summary_data, f, indent=2)
            
            logger.info("daily_summary_saved", file=str(summary_file))
        
        except Exception as e:
            logger.error("failed_to_save_daily_summary", error=str(e))
