"""Telegram alerts with rate limiting and batching."""
from telegram import Bot
from telegram.error import TelegramError
import structlog
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = structlog.get_logger()


class TelegramAlerter:
    """
    Send alerts to Telegram with intelligent rate limiting.
    
    Features:
    - Per-alert-type batching (max 1 per 10 seconds for same type)
    - Configurable rate limits
    - Graceful degradation if Telegram unavailable
    """
    
    def __init__(self, token: str, chat_id: str, rate_limit_seconds: int = 10):
        self.bot = Bot(token=token)
        self.chat_id = chat_id
        self.rate_limit_seconds = rate_limit_seconds
        
        # Track last alert time by type
        self.last_alert_time: Dict[str, datetime] = {}
        
        # Stats
        self.stats = {
            'sent': 0,
            'rate_limited': 0,
            'failed': 0
        }
    
    async def send_alert(self, message: str, alert_type: str = "general", force: bool = False):
        """
        Send alert message with rate limiting.
        
        Args:
            message: Alert message (HTML formatting supported)
            alert_type: Type of alert (for batching - e.g., "startup", "edge", "trade", "position", "error")
            force: Skip rate limiting (for critical alerts)
        """
        # Check rate limit (unless forced)
        if not force and alert_type in self.last_alert_time:
            time_since_last = datetime.now() - self.last_alert_time[alert_type]
            if time_since_last < timedelta(seconds=self.rate_limit_seconds):
                self.stats['rate_limited'] += 1
                logger.debug(
                    "telegram_alert_rate_limited",
                    alert_type=alert_type,
                    seconds_since_last=round(time_since_last.total_seconds(), 1)
                )
                return
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
            
            # Update tracking
            self.last_alert_time[alert_type] = datetime.now()
            self.stats['sent'] += 1
            
            logger.info("telegram_alert_sent", alert_type=alert_type)
            
        except TelegramError as e:
            self.stats['failed'] += 1
            logger.error("telegram_alert_failed", error=str(e), alert_type=alert_type)
    
    def get_stats(self) -> Dict:
        """Get alerter statistics."""
        return self.stats.copy()
