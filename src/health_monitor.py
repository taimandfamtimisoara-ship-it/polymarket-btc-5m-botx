"""Health monitoring and auto-restart system."""
import asyncio
import psutil
import os
import sys
import structlog
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable
from enum import Enum

logger = structlog.get_logger()


class HealthStatus(Enum):
    """Overall health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth:
    """Health status of a single component."""
    
    def __init__(self, name: str, healthy: bool, message: str = "", latency_ms: Optional[float] = None):
        self.name = name
        self.healthy = healthy
        self.message = message
        self.latency_ms = latency_ms
        self.checked_at = datetime.now()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'healthy': self.healthy,
            'message': self.message,
            'latency_ms': self.latency_ms,
            'checked_at': self.checked_at.isoformat()
        }


class HealthMonitor:
    """
    Bot health monitoring and auto-restart system.
    
    Features:
    - Fast health checks (<100ms total)
    - Watchdog for auto-restart
    - Component-level health tracking
    - Telegram alerts on issues
    """
    
    def __init__(self, 
                 price_feed,
                 market_fetcher,
                 telegram_alerter=None,
                 heartbeat_timeout_seconds: int = 60,
                 memory_limit_mb: int = 500):
        self.price_feed = price_feed
        self.market_fetcher = market_fetcher
        self.telegram_alerter = telegram_alerter
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.memory_limit_mb = memory_limit_mb
        
        # Main loop heartbeat tracking
        self.last_heartbeat: Optional[datetime] = None
        self.heartbeat_enabled = False
        
        # Watchdog control
        self.watchdog_running = False
        self.watchdog_task: Optional[asyncio.Task] = None
        
        # Restart callback
        self.restart_callback: Optional[Callable] = None
        
        # Stats
        self.stats = {
            'health_checks': 0,
            'warnings': 0,
            'errors': 0,
            'restarts': 0,
            'last_warning': None,
            'last_error': None
        }
        
        # Process info
        self.process = psutil.Process(os.getpid())
        self.start_time = datetime.now()
    
    def heartbeat(self):
        """
        Record heartbeat from main loop.
        Call this at the start of each trading cycle.
        """
        self.last_heartbeat = datetime.now()
        if not self.heartbeat_enabled:
            self.heartbeat_enabled = True
            logger.info("health_monitor_heartbeat_enabled")
    
    async def check_health(self) -> Dict:
        """
        Comprehensive health check (fast - target <100ms).
        
        Returns:
            Health report with overall status and component details
        """
        check_start = datetime.now()
        self.stats['health_checks'] += 1
        
        components = []
        
        # 1. Price feed connection check
        price_feed_health = self._check_price_feed()
        components.append(price_feed_health)
        
        # 2. Main loop heartbeat check
        heartbeat_health = self._check_heartbeat()
        components.append(heartbeat_health)
        
        # 3. API accessibility check
        api_health = await self._check_api_access()
        components.append(api_health)
        
        # 4. Memory usage check
        memory_health = self._check_memory()
        components.append(memory_health)
        
        # Determine overall status
        overall_status = self._calculate_overall_status(components)
        
        # Calculate check duration
        check_duration_ms = (datetime.now() - check_start).total_seconds() * 1000
        
        # Build report
        report = {
            'status': overall_status.value,
            'components': [c.to_dict() for c in components],
            'check_duration_ms': round(check_duration_ms, 2),
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
            'stats': self.stats.copy(),
            'timestamp': datetime.now().isoformat()
        }
        
        # Log if slow
        if check_duration_ms > 100:
            logger.warning("slow_health_check", duration_ms=check_duration_ms)
        
        return report
    
    def _check_price_feed(self) -> ComponentHealth:
        """Check price feed health."""
        # Check connection
        if not self.price_feed.is_connected:
            self.stats['errors'] += 1
            self.stats['last_error'] = 'price_feed_disconnected'
            return ComponentHealth(
                name="price_feed",
                healthy=False,
                message="WebSocket disconnected"
            )
        
        # Check last update time
        latency_ms = self.price_feed.get_latency_ms()
        
        if latency_ms is None:
            self.stats['warnings'] += 1
            self.stats['last_warning'] = 'no_price_data'
            return ComponentHealth(
                name="price_feed",
                healthy=False,
                message="No price data received",
                latency_ms=None
            )
        
        # Check if data is stale (>30 seconds)
        if latency_ms > 30000:  # 30 seconds
            self.stats['warnings'] += 1
            self.stats['last_warning'] = 'stale_price_data'
            return ComponentHealth(
                name="price_feed",
                healthy=False,
                message=f"Price data stale ({latency_ms/1000:.1f}s old)",
                latency_ms=latency_ms
            )
        
        # Healthy
        return ComponentHealth(
            name="price_feed",
            healthy=True,
            message="Connected and receiving data",
            latency_ms=latency_ms
        )
    
    def _check_heartbeat(self) -> ComponentHealth:
        """Check main loop heartbeat."""
        if not self.heartbeat_enabled:
            return ComponentHealth(
                name="main_loop",
                healthy=True,
                message="Heartbeat not yet enabled"
            )
        
        if self.last_heartbeat is None:
            self.stats['warnings'] += 1
            self.stats['last_warning'] = 'no_heartbeat'
            return ComponentHealth(
                name="main_loop",
                healthy=False,
                message="No heartbeat received"
            )
        
        # Check heartbeat age
        heartbeat_age_seconds = (datetime.now() - self.last_heartbeat).total_seconds()
        
        # Critical: no heartbeat for 60+ seconds
        if heartbeat_age_seconds > self.heartbeat_timeout_seconds:
            self.stats['errors'] += 1
            self.stats['last_error'] = 'heartbeat_timeout'
            return ComponentHealth(
                name="main_loop",
                healthy=False,
                message=f"No heartbeat for {heartbeat_age_seconds:.1f}s (threshold: {self.heartbeat_timeout_seconds}s)"
            )
        
        # Warning: no heartbeat for 30+ seconds
        if heartbeat_age_seconds > 30:
            self.stats['warnings'] += 1
            self.stats['last_warning'] = 'heartbeat_delayed'
            return ComponentHealth(
                name="main_loop",
                healthy=True,  # Still healthy but degraded
                message=f"Heartbeat delayed ({heartbeat_age_seconds:.1f}s)"
            )
        
        # Healthy
        return ComponentHealth(
            name="main_loop",
            healthy=True,
            message=f"Running (last heartbeat {heartbeat_age_seconds:.1f}s ago)"
        )
    
    async def _check_api_access(self) -> ComponentHealth:
        """Check if we can access Polymarket API."""
        if not self.market_fetcher:
            return ComponentHealth(
                name="api_access",
                healthy=True,
                message="Market fetcher not initialized"
            )
        
        try:
            # Quick test: try to fetch markets (with short timeout)
            check_start = datetime.now()
            
            # This should be fast if API is responsive
            markets = await asyncio.wait_for(
                self.market_fetcher.get_active_markets(),
                timeout=5.0  # 5 second timeout
            )
            
            latency_ms = (datetime.now() - check_start).total_seconds() * 1000
            
            if markets is None or len(markets) == 0:
                self.stats['warnings'] += 1
                self.stats['last_warning'] = 'no_markets_found'
                return ComponentHealth(
                    name="api_access",
                    healthy=True,  # API works, just no markets
                    message="API accessible, no active markets found",
                    latency_ms=latency_ms
                )
            
            return ComponentHealth(
                name="api_access",
                healthy=True,
                message=f"API accessible ({len(markets)} markets)",
                latency_ms=latency_ms
            )
            
        except asyncio.TimeoutError:
            self.stats['errors'] += 1
            self.stats['last_error'] = 'api_timeout'
            return ComponentHealth(
                name="api_access",
                healthy=False,
                message="API request timeout (>5s)"
            )
        except Exception as e:
            self.stats['errors'] += 1
            self.stats['last_error'] = 'api_error'
            return ComponentHealth(
                name="api_access",
                healthy=False,
                message=f"API error: {str(e)[:100]}"
            )
    
    def _check_memory(self) -> ComponentHealth:
        """Check memory usage."""
        try:
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB
            
            if memory_mb > self.memory_limit_mb:
                self.stats['warnings'] += 1
                self.stats['last_warning'] = 'high_memory'
                return ComponentHealth(
                    name="memory",
                    healthy=False,
                    message=f"High memory usage: {memory_mb:.1f}MB (limit: {self.memory_limit_mb}MB)"
                )
            
            return ComponentHealth(
                name="memory",
                healthy=True,
                message=f"Memory usage: {memory_mb:.1f}MB / {self.memory_limit_mb}MB"
            )
            
        except Exception as e:
            logger.error("memory_check_failed", error=str(e))
            return ComponentHealth(
                name="memory",
                healthy=True,
                message="Memory check unavailable"
            )
    
    def _calculate_overall_status(self, components: list) -> HealthStatus:
        """Calculate overall health status from components."""
        unhealthy_count = sum(1 for c in components if not c.healthy)
        
        if unhealthy_count == 0:
            return HealthStatus.HEALTHY
        
        # If price feed or main loop is down, we're unhealthy
        critical_components = ['price_feed', 'main_loop']
        for component in components:
            if component.name in critical_components and not component.healthy:
                return HealthStatus.UNHEALTHY
        
        # Otherwise degraded
        return HealthStatus.DEGRADED
    
    async def start_watchdog(self, restart_callback: Optional[Callable] = None):
        """
        Start watchdog task to monitor health and auto-restart if needed.
        
        Args:
            restart_callback: Async function to call for graceful restart
        """
        if self.watchdog_running:
            logger.warning("watchdog_already_running")
            return
        
        self.restart_callback = restart_callback
        self.watchdog_running = True
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())
        
        logger.info("health_watchdog_started", 
                   heartbeat_timeout=self.heartbeat_timeout_seconds,
                   memory_limit_mb=self.memory_limit_mb)
    
    async def stop_watchdog(self):
        """Stop watchdog task."""
        self.watchdog_running = False
        
        if self.watchdog_task:
            self.watchdog_task.cancel()
            try:
                await self.watchdog_task
            except asyncio.CancelledError:
                pass
        
        logger.info("health_watchdog_stopped")
    
    async def _watchdog_loop(self):
        """
        Watchdog loop - monitors health and triggers restart if needed.
        
        Checks every 15 seconds.
        """
        try:
            while self.watchdog_running:
                await asyncio.sleep(15)  # Check every 15 seconds
                
                # Run health check
                health_report = await self.check_health()
                
                # If unhealthy, send alert and potentially restart
                if health_report['status'] == HealthStatus.UNHEALTHY.value:
                    logger.error("bot_unhealthy", report=health_report)
                    
                    # Send Telegram alert
                    if self.telegram_alerter:
                        unhealthy_components = [
                            c for c in health_report['components']
                            if not c['healthy']
                        ]
                        
                        alert_msg = "🚨 <b>Bot Health Critical</b>\n\n"
                        alert_msg += f"Status: <b>{health_report['status'].upper()}</b>\n\n"
                        alert_msg += "<b>Failed Components:</b>\n"
                        
                        for component in unhealthy_components:
                            alert_msg += f"❌ <b>{component['name']}</b>: {component['message']}\n"
                        
                        await self.telegram_alerter.send_alert(
                            alert_msg,
                            alert_type="health_critical",
                            force=True  # Always send critical health alerts
                        )
                    
                    # Trigger restart if callback provided
                    if self.restart_callback:
                        logger.warning("triggering_auto_restart")
                        
                        if self.telegram_alerter:
                            await self.telegram_alerter.send_alert(
                                "🔄 <b>Auto-Restart Triggered</b>\n\n"
                                "Attempting graceful restart...",
                                alert_type="restart",
                                force=True
                            )
                        
                        self.stats['restarts'] += 1
                        
                        # Call restart callback
                        try:
                            await self.restart_callback()
                        except Exception as e:
                            logger.error("restart_callback_failed", error=str(e))
                            
                            if self.telegram_alerter:
                                await self.telegram_alerter.send_alert(
                                    f"❌ <b>Restart Failed</b>\n\n"
                                    f"Error: <code>{str(e)[:150]}</code>\n\n"
                                    "Manual intervention required!",
                                    alert_type="restart_failed",
                                    force=True
                                )
                
                # Send warning alerts for degraded status
                elif health_report['status'] == HealthStatus.DEGRADED.value:
                    logger.warning("bot_health_degraded", report=health_report)
                    
                    if self.telegram_alerter:
                        degraded_components = [
                            c for c in health_report['components']
                            if not c['healthy']
                        ]
                        
                        alert_msg = "⚠️ <b>Bot Health Degraded</b>\n\n"
                        
                        for component in degraded_components:
                            alert_msg += f"⚠️ <b>{component['name']}</b>: {component['message']}\n"
                        
                        await self.telegram_alerter.send_alert(
                            alert_msg,
                            alert_type="health_warning"
                        )
        
        except asyncio.CancelledError:
            logger.info("watchdog_cancelled")
        except Exception as e:
            logger.error("watchdog_error", error=str(e))


# Singleton instance (initialized by main bot)
health_monitor: Optional[HealthMonitor] = None


def init_health_monitor(price_feed, market_fetcher, telegram_alerter=None) -> HealthMonitor:
    """Initialize global health monitor instance."""
    global health_monitor
    health_monitor = HealthMonitor(price_feed, market_fetcher, telegram_alerter)
    return health_monitor
