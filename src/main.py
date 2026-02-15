"""Main orchestrator - BTC 5-minute trading bot."""
import asyncio
import os
import structlog
from datetime import datetime
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

from config import config
from price_feed import price_feed
from edge_detector import edge_detector
from execution_engine import init_execution_engine
from market_fetcher import init_market_fetcher
from resolution_tracker import init_resolution_tracker
from pnl_calculator import init_pnl_calculator
from telegram_alerts import TelegramAlerter
from rate_limiter import init_rate_limiter
from health_monitor import init_health_monitor
from survival_brain import SurvivalBrain
from paper_trader import PaperTrader
import dashboard_api

# Setup logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()


class BTCBot:
    """
    BTC 5-minute trading bot orchestrator.
    
    Flow:
    1. Connect to real-time BTC price feed (WebSocket)
    2. Fetch active 5-minute markets from Polymarket
    3. Scan markets for edges (price vs odds mismatch)
    4. Execute profitable opportunities FAST
    5. Monitor positions and update dashboard
    
    Target: <100ms from edge detection to order execution
    """
    
    def __init__(self):
        self.clob_client = None
        self.execution_engine = None
        self.market_fetcher = None
        self.resolution_tracker = None
        self.pnl_calculator = None
        self.telegram_alerter = None
        self.health_monitor = None
        self.survival_brain = None
        self.paper_trader = None
        self.is_running = False
        self.restart_requested = False
        self.last_survival_check = None
        self.last_resolution_check = None
        self.stats = {
            'edges_detected': 0,
            'orders_executed': 0,
            'total_pnl': 0.0,
            'started_at': None
        }
        
    async def initialize(self):
        """Initialize all components."""
        logger.info("bot_initializing", env=config.ENVIRONMENT)
        
        try:
            # 0. Initialize rate limiter (must be first!)
            init_rate_limiter()
            logger.info("rate_limiter_initialized")
            
            # 1. Initialize Telegram alerter (if configured)
            if config.telegram_bot_token and config.telegram_chat_id:
                self.telegram_alerter = TelegramAlerter(
                    token=config.telegram_bot_token,
                    chat_id=config.telegram_chat_id,
                    rate_limit_seconds=10
                )
                logger.info("telegram_alerts_enabled")
            else:
                logger.warning("telegram_alerts_disabled", reason="Missing credentials")
            
            # 1.5. Initialize Survival Brain (needs telegram_alerter)
            self.survival_brain = SurvivalBrain(
                initial_capital=config.initial_bankroll,
                telegram_alerter=self.telegram_alerter
            )
            logger.info("survival_brain_initialized", initial_capital=config.initial_bankroll)
            
            # 1.6. Initialize Paper Trader (if in paper mode)
            if config.ENVIRONMENT == "paper":
                self.paper_trader = PaperTrader(
                    survival_brain=self.survival_brain,
                    telegram_alerter=self.telegram_alerter,
                    initial_capital=config.initial_bankroll
                )
                logger.info("paper_trader_initialized", mode="OBSERVATION")
            
            # Set survival brain in dashboard API
            dashboard_api.set_survival_brain(self.survival_brain)
            
            # 2. Initialize Polymarket client
            self.clob_client = ClobClient(
                key=config.POLYMARKET_PRIVATE_KEY,
                chain_id=POLYGON,
                host=config.POLYMARKET_HOST
            )
            
            # 3. Initialize execution engine
            self.execution_engine = init_execution_engine(self.clob_client)
            
            # 4. Initialize market fetcher
            self.market_fetcher = init_market_fetcher(self.clob_client)
            
            # 4.5. OPTIMIZATION: Start background market refresh for instant cache hits
            await self.market_fetcher.start_background_refresh()
            logger.info("background_market_refresh_started")
            
            # 5. Initialize resolution tracker
            self.resolution_tracker = init_resolution_tracker(self.clob_client, self.execution_engine)
            
            # 6. Initialize PnL calculator
            self.pnl_calculator = init_pnl_calculator(self.clob_client)
            
            # 7. Attach resolution tracker, PnL calculator, telegram alerter, and survival brain to execution engine
            self.execution_engine.set_resolution_tracker(self.resolution_tracker)
            self.execution_engine.set_pnl_calculator(self.pnl_calculator)
            if self.telegram_alerter:
                self.execution_engine.set_telegram_alerter(self.telegram_alerter)
            if self.survival_brain:
                self.execution_engine.set_survival_brain(self.survival_brain)
            
            # 8. Start resolution tracker background task
            await self.resolution_tracker.start()
            
            # 9. Connect to BTC price feed
            await price_feed.connect()
            
            # Wait for first price
            retry_count = 0
            while not price_feed.current_price and retry_count < 10:
                await asyncio.sleep(0.5)
                retry_count += 1
            
            if not price_feed.current_price:
                raise Exception("Failed to get initial BTC price")
            
            # 10. Initialize health monitor
            self.health_monitor = init_health_monitor(
                price_feed=price_feed,
                market_fetcher=self.market_fetcher,
                telegram_alerter=self.telegram_alerter
            )
            
            # Start watchdog with restart callback
            await self.health_monitor.start_watchdog(
                restart_callback=self._graceful_restart
            )
            
            logger.info(
                "bot_initialized",
                btc_price=price_feed.current_price,
                feed_connected=price_feed.is_connected,
                health_monitor_enabled=True
            )
            
            self.stats['started_at'] = datetime.now()
            
            # Send startup alert
            if self.telegram_alerter:
                mode_description = "PAPER (Observation Mode)" if config.ENVIRONMENT == "paper" else "LIVE (Real Money)"
                startup_msg = (
                    f"🚀 <b>BTC 5m Bot Started</b>\n\n"
                    f"Mode: <b>{mode_description}</b>\n"
                    f"BTC Price: <b>${price_feed.current_price:,.2f}</b>\n"
                    f"Feed: <b>{'✅ Connected' if price_feed.is_connected else '❌ Disconnected'}</b>"
                )
                
                if config.ENVIRONMENT == "paper":
                    startup_msg += (
                        f"\n\n📊 <b>Paper Trading Active</b>\n"
                        f"• Tracking all decisions\n"
                        f"• Simulating positions\n"
                        f"• No real money at risk\n"
                        f"• Initial capital: ${config.initial_bankroll:.2f}"
                    )
                
                await self.telegram_alerter.send_alert(
                    startup_msg,
                    alert_type="startup",
                    force=True  # Always send startup
                )
            
        except Exception as e:
            logger.error("bot_init_failed", error=str(e))
            
            # Send error alert
            if self.telegram_alerter:
                await self.telegram_alerter.send_alert(
                    f"❌ <b>Bot Initialization Failed</b>\n\n"
                    f"Error: <code>{str(e)[:200]}</code>",
                    alert_type="error",
                    force=True
                )
            
            raise
    
    async def run(self):
        """Main bot loop - OPTIMIZED FOR SPEED."""
        self.is_running = True
        logger.info("bot_started", mode=config.ENVIRONMENT)
        
        # Print mode warning
        if config.ENVIRONMENT == "paper":
            logger.warning("PAPER_TRADING_MODE", message="No real orders will be placed")
        else:
            logger.warning("LIVE_TRADING_MODE", message="REAL MONEY AT RISK")
        
        try:
            while self.is_running and not self.restart_requested:
                await self._trading_cycle()
                
                # Brief pause between cycles (configurable)
                # OPTIMIZED: Reduced from 100ms to 5ms for sub-15ms reaction time
                await asyncio.sleep(0.005)  # 5ms cycle time
                
        except KeyboardInterrupt:
            logger.info("bot_stopped_by_user")
        except Exception as e:
            logger.error("bot_error", error=str(e))
        finally:
            await self.shutdown()
            
            # If restart was requested, re-initialize and run again
            if self.restart_requested:
                logger.info("bot_restarting")
                
                # Brief pause before restart
                await asyncio.sleep(2)
                
                try:
                    # Reset restart flag
                    self.restart_requested = False
                    
                    # Re-initialize
                    await self.initialize()
                    
                    # Run again
                    await self.run()
                    
                except Exception as e:
                    logger.error("bot_restart_failed", error=str(e))
                    
                    if self.telegram_alerter:
                        await self.telegram_alerter.send_alert(
                            f"❌ <b>Bot Restart Failed</b>\n\n"
                            f"Error: <code>{str(e)[:200]}</code>\n\n"
                            "Manual intervention required!",
                            alert_type="restart_failed",
                            force=True
                        )
    
    async def _trading_cycle(self):
        """
        Single trading cycle - FAST.
        
        1. Get current BTC price
        2. Fetch active markets
        3. Scan for edges
        4. Execute opportunities
        5. Periodic survival checks
        
        Target: <50ms per cycle (when no orders)
        """
        cycle_start = datetime.now()
        
        # Record heartbeat for health monitoring
        if self.health_monitor:
            self.health_monitor.heartbeat()
        
        # Periodic survival brain tick (every 5 minutes)
        if self.survival_brain:
            now = datetime.now()
            if self.last_survival_check is None or (now - self.last_survival_check).total_seconds() >= 300:
                await self.survival_brain.tick()
                self.last_survival_check = now
                
                # Log current survival status
                status = self.survival_brain.get_survival_status()
                logger.info(
                    "survival_status",
                    state=status.state.value,
                    capital=round(status.current_capital, 2),
                    capital_pct=round(status.capital_pct, 1),
                    kelly_modifier=round(status.kelly_modifier, 2),
                    min_edge=round(status.min_edge_threshold, 1)
                )
        
        # Periodic paper trade resolution check (every 30 seconds in paper mode)
        if self.paper_trader:
            now = datetime.now()
            if self.last_resolution_check is None or (now - self.last_resolution_check).total_seconds() >= 30:
                try:
                    resolved = await self.paper_trader.check_resolutions(self.clob_client)
                    if resolved:
                        logger.info("paper_trades_resolved", count=len(resolved))
                except Exception as e:
                    logger.error("paper_resolution_check_failed", error=str(e))
                finally:
                    self.last_resolution_check = now
        
        try:
            # 1. Get current BTC price (instant - local)
            current_price = price_feed.get_current_price()
            
            if not current_price:
                logger.warning("no_price_data")
                return
            
            # 2. OPTIMIZED: Parallel fetch markets and get price history
            # This reduces sequential wait time significantly
            markets_task = self.market_fetcher.get_active_markets()
            price_history = price_feed.get_price_history()  # Instant - local deque
            
            # Await market fetch (happens in parallel with any other async ops)
            markets = await markets_task
            
            if not markets:
                logger.debug("no_active_markets")
                return
            
            # 3. Scan for edges (with momentum indicators)
            # Edge detection is CPU-bound, runs synchronously
            edges = edge_detector.scan_markets(current_price, markets, price_history)
            
            self.stats['edges_detected'] += len(edges)
            
            if not edges:
                # No opportunities - continue
                return
            
            # 5. Prioritize edges
            sorted_edges = edge_detector.prioritize_edges(edges)
            
            # Alert on large edges (>5%)
            if self.telegram_alerter:
                for edge in sorted_edges:
                    if edge.edge_pct > 5.0:
                        # Build alert message with indicators
                        alert_msg = (
                            f"🔥 <b>Large Edge Detected!</b>\n\n"
                            f"Market: <code>{edge.market_id[:30]}...</code>\n"
                            f"Edge: <b>{edge.edge_pct:.2f}%</b>\n"
                            f"Confidence: <b>{edge.confidence:.2f}</b>\n"
                            f"Direction: <b>{edge.direction}</b>\n"
                            f"BTC Price: <b>${edge.current_price:,.2f}</b>\n"
                            f"Market {edge.direction} Price: <b>{edge.market_yes_price if edge.direction == 'YES' else edge.market_no_price:.4f}</b>"
                        )
                        
                        # Add indicator info if available
                        if edge.indicators:
                            alert_msg += (
                                f"\n\n📊 <b>Indicators:</b>\n"
                                f"RSI: <b>{edge.indicators.rsi:.1f if edge.indicators.rsi else 'N/A'}</b> ({edge.indicators.rsi_signal})\n"
                                f"MACD: <b>{edge.indicators.macd_trend}</b>\n"
                                f"Alignment: <b>{edge.indicators.alignment_score:.2f}</b>"
                            )
                        
                        await self.telegram_alerter.send_alert(
                            alert_msg,
                            alert_type="edge"  # Rate limited to 1 per 10 seconds
                        )
                        break  # Only alert on the largest edge
            
            # 6. Execute top edges (up to max concurrent positions)
            if config.ENVIRONMENT == "paper":
                # Paper trading mode - record trades instead of executing
                for edge in sorted_edges:
                    # Check if survival brain approves this trade
                    should_take, reason = self.survival_brain.should_take_trade(
                        edge=edge.edge_pct,
                        market_type="btc_5min",
                        hour=datetime.now().hour
                    )
                    
                    if should_take:
                        # Record paper trade
                        result = await self.paper_trader.record_trade(edge)
                        if result['status'] == 'recorded':
                            self.stats['orders_executed'] += 1
                            logger.info(
                                "paper_trade_recorded",
                                trade_id=result['trade_id'],
                                edge_pct=round(edge.edge_pct, 2),
                                direction=edge.direction
                            )
                    else:
                        logger.debug(
                            "paper_trade_rejected",
                            edge_pct=round(edge.edge_pct, 2),
                            reason=reason
                        )
            else:
                # Live trading mode - execute real trades
                available_slots = (
                    config.MAX_CONCURRENT_POSITIONS - 
                    self.execution_engine.get_position_count()
                )
                
                for edge in sorted_edges[:available_slots]:
                    # Check latency threshold
                    feed_latency = price_feed.get_latency_ms()
                    if feed_latency and feed_latency > config.MAX_LATENCY_MS:
                        logger.warning(
                            "latency_too_high",
                            latency_ms=feed_latency,
                            threshold=config.MAX_LATENCY_MS
                        )
                        continue
                    
                    # Execute
                    result = await self.execution_engine.execute_edge(edge)
                    if result:
                        self.stats['orders_executed'] += 1
            
            # OPTIMIZATION: Log cycle time and latency metrics
            cycle_time_ms = (datetime.now() - cycle_start).total_seconds() * 1000
            
            # Log detailed timing for optimization tracking
            if edges:
                logger.info(
                    "cycle_with_edges",
                    cycle_time_ms=round(cycle_time_ms, 2),
                    edges=len(edges),
                    price_feed_latency_ms=round(price_feed.get_price_update_latency_ms() or 0, 2),
                    avg_feed_latency_ms=round(price_feed.get_avg_latency_ms() or 0, 2)
                )
            
            # Warn on slow cycles (>50ms when optimized)
            if cycle_time_ms > 50:
                logger.warning(
                    "slow_cycle",
                    time_ms=round(cycle_time_ms, 2),
                    edges=len(edges),
                    target_ms=50
                )
            
        except Exception as e:
            logger.error("cycle_error", error=str(e))
            
            # Alert on errors (rate limited)
            if self.telegram_alerter:
                await self.telegram_alerter.send_alert(
                    f"⚠️ <b>Trading Cycle Error</b>\n\n"
                    f"Error: <code>{str(e)[:150]}</code>",
                    alert_type="error"  # Rate limited to 1 per 10 seconds
                )
    
    async def _graceful_restart(self):
        """
        Graceful restart triggered by health watchdog.
        
        Preserves state and attempts clean restart.
        """
        logger.warning("graceful_restart_initiated")
        
        # Set restart flag to trigger restart after shutdown
        self.restart_requested = True
        
        # Stop main loop
        self.is_running = False
        
        # Note: shutdown() will be called by run() finally block
        # and then restart logic in run() will handle re-initialization
    
    async def shutdown(self):
        """Clean shutdown."""
        logger.info("bot_shutting_down")
        
        self.is_running = False
        
        # Stop health watchdog
        if self.health_monitor:
            await self.health_monitor.stop_watchdog()
        
        # Send survival brain daily report (unless restarting)
        if self.survival_brain and not self.restart_requested:
            try:
                await self.survival_brain.send_daily_survival_report()
            except Exception as e:
                logger.error("survival_daily_report_failed", error=str(e))
        
        # Send paper trading summary (unless restarting)
        if self.paper_trader and not self.restart_requested:
            try:
                await self.paper_trader.send_daily_summary()
            except Exception as e:
                logger.error("paper_trading_summary_failed", error=str(e))
        
        # Calculate runtime stats
        runtime = None
        if self.stats['started_at']:
            runtime = (datetime.now() - self.stats['started_at']).total_seconds()
        
        # Send shutdown alert (unless restarting)
        if self.telegram_alerter and not self.restart_requested:
            win_rate = 0.0
            if self.execution_engine and self.execution_engine.total_trades > 0:
                win_rate = (self.execution_engine.wins / self.execution_engine.total_trades) * 100
            
            await self.telegram_alerter.send_alert(
                f"🛑 <b>Bot Shutting Down</b>\n\n"
                f"Runtime: <b>{runtime/60:.1f} minutes</b>\n"
                f"Edges Detected: <b>{self.stats['edges_detected']}</b>\n"
                f"Orders Executed: <b>{self.stats['orders_executed']}</b>\n"
                f"Win Rate: <b>{win_rate:.1f}%</b>\n"
                f"Total P&L: <b>${self.execution_engine.total_pnl if self.execution_engine else 0:.2f}</b>",
                alert_type="shutdown",
                force=True  # Always send shutdown
            )
        
        # Stop background market refresh
        if self.market_fetcher:
            await self.market_fetcher.stop_background_refresh()
        
        # Stop resolution tracker
        if self.resolution_tracker:
            await self.resolution_tracker.stop()
        
        # Close price feed
        await price_feed.close()
        
        # Print stats
        runtime = None
        if self.stats['started_at']:
            runtime = (datetime.now() - self.stats['started_at']).total_seconds()
        
        logger.info(
            "bot_shutdown_complete",
            runtime_seconds=round(runtime, 1) if runtime else None,
            edges_detected=self.stats['edges_detected'],
            orders_executed=self.stats['orders_executed'],
            avg_execution_time_ms=round(
                self.execution_engine.get_avg_execution_time_ms() or 0, 2
            )
        )
    
    def get_stats(self) -> dict:
        """Get bot statistics (for dashboard)."""
        # Get execution engine stats (includes merged speed_engine metrics and resolution stats)
        engine_stats = self.execution_engine.get_status()
        
        stats = {
            **self.stats,
            **engine_stats,
            'current_price': price_feed.get_current_price(),
            'feed_latency_ms': price_feed.get_latency_ms(),
            # OPTIMIZATION: Add comprehensive latency metrics
            'latency_stats': price_feed.get_latency_stats()
        }
        
        # Add resolution tracker stats separately for clarity (also in engine_stats.resolution_stats)
        if self.resolution_tracker:
            stats['resolution_tracker'] = self.resolution_tracker.get_stats()
        
        # Add health monitor stats
        if self.health_monitor:
            stats['health_monitor'] = self.health_monitor.stats.copy()
        
        # Add survival brain stats
        if self.survival_brain:
            survival_status = self.survival_brain.get_survival_status()
            stats['survival'] = survival_status.to_dict()
        
        # Add paper trading stats
        if self.paper_trader:
            stats['paper_trading'] = self.paper_trader.get_stats()
        
        return stats


async def start_dashboard():
    """Start the dashboard API server."""
    import uvicorn
    config = uvicorn.Config(
        dashboard_api.app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="warning"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Entry point."""
    bot = BTCBot()
    
    try:
        await bot.initialize()
        
        # Run bot and dashboard concurrently
        await asyncio.gather(
            bot.run(),
            start_dashboard()
        )
    except Exception as e:
        logger.error("bot_failed", error=str(e))
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
