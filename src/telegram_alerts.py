"""Telegram alerts."""
from telegram import Bot
from telegram.error import TelegramError
import structlog

logger = structlog.get_logger()


class TelegramAlerter:
    """Send alerts to Telegram."""
    
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id
    
    async def send_alert(self, message: str):
        """Send alert message."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info("telegram_alert_sent")
        except TelegramError as e:
            logger.error("telegram_alert_failed", error=str(e))
