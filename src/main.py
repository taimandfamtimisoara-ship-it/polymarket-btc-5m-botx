"""Main orchestrator - BTC 5-minute trading bot."""
import asyncio
import structlog
from datetime import datetime
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

from config import config
from price_feed import price_feed
from edge_detector import edge_detector
from execution_engine import init_execution_engine
from market_fetcher import init_market_fetcher

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
        self.is_running = False
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
            # 1. Initialize Polymarket client
            self.clob_client = ClobClient(
                key=config.POLYMARKET_PRIVATE_KEY,
                chain_id=POLYGON,
                host=config.POLYMARKET_HOST
            )
            
            # 2. Initialize execution engine
            self.execution_engine = init_execution_engine(self.clob_client)
            
            # 3. Initialize market fetcher
            self.market_fetcher = init_market_fetcher(self.clob_client)
            
            # 4. Connect to BTC price feed
            await price_feed.connect()
            
            # Wait for first price
            retry_count = 0
            while not price_feed.current_price and retry_count < 10:
                await asyncio.sleep(0.5)
                retry_count += 1
            
            if not price_feed.current_price:
                raise Exception("Failed to get initial BTC price")
            
            logger.info(
                "bot_initialized",
                btc_price=price_feed.current_price,
                feed_connected=price_feed.is_connected
            )
            
            self.stats['started_at'] = datetime.now()
            
        except Exception as e:
            logger.error("bot_init_failed", error=str(e))
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
            while self.is_running:
                await self._trading_cycle()
                
                # Brief pause between cycles (configurable)
                await asyncio.sleep(0.1)  # 100ms cycle time
                
        except KeyboardInterrupt:
            logger.info("bot_stopped_by_user")
        except Exception as e:
            logger.error("bot_error", error=str(e))
        finally:
            await self.shutdown()
    
    async def _trading_cycle(self):
        """
        Single trading cycle - FAST.
        
        1. Get current BTC price
        2. Fetch active markets
        3. Scan for edges
        4. Execute opportunities
        
        Target: <50ms per cycle (when no orders)
        """
        cycle_start = datetime.now()
        
        try:
            # 1. Get current BTC price
            current_price = price_feed.get_current_price()
            
            if not current_price:
                logger.warning("no_price_data")
                return
            
            # 2. Fetch active markets
            markets = await self.market_fetcher.get_active_markets()
            
            if not markets:
                logger.debug("no_active_markets")
                return
            
            # 3. Scan for edges
            edges = edge_detector.scan_markets(current_price, markets)
            
            self.stats['edges_detected'] += len(edges)
            
            if not edges:
                # No opportunities - continue
                return
            
            # 4. Prioritize edges
            sorted_edges = edge_detector.prioritize_edges(edges)
            
            # 5. Execute top edges (up to max concurrent positions)
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
                if config.ENVIRONMENT == "paper":
                    logger.info(
                        "paper_trade",
                        edge=str(edge),
                        note="Would execute in live mode"
                    )
                else:
                    result = await self.execution_engine.execute_edge(edge)
                    if result:
                        self.stats['orders_executed'] += 1
            
            # Log cycle time
            cycle_time_ms = (datetime.now() - cycle_start).total_seconds() * 1000
            
            if cycle_time_ms > 100:
                logger.warning(
                    "slow_cycle",
                    time_ms=round(cycle_time_ms, 2),
                    edges=len(edges)
                )
            
        except Exception as e:
            logger.error("cycle_error", error=str(e))
    
    async def shutdown(self):
        """Clean shutdown."""
        logger.info("bot_shutting_down")
        
        self.is_running = False
        
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
        return {
            **self.stats,
            'current_price': price_feed.get_current_price(),
            'feed_latency_ms': price_feed.get_latency_ms(),
            'active_positions': self.execution_engine.get_position_count(),
            'avg_execution_time_ms': self.execution_engine.get_avg_execution_time_ms()
        }


async def main():
    """Entry point."""
    bot = BTCBot()
    
    try:
        await bot.initialize()
        await bot.run()
    except Exception as e:
        logger.error("bot_failed", error=str(e))
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
