"""Configuration for BTC 5m speed bot."""
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Settings from environment variables."""
    
    # Polygon Wallet
    polygon_wallet_private_key: str = Field(..., alias="POLYGON_WALLET_PRIVATE_KEY")
    polymarket_funder_address: Optional[str] = Field(None, alias="POLYMARKET_FUNDER_ADDRESS")
    
    # Anthropic (for market analysis)
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    
    # Telegram
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(..., alias="TELEGRAM_CHAT_ID")
    
    # Binance (price feed)
    binance_api_key: Optional[str] = Field(None, alias="BINANCE_API_KEY")
    binance_api_secret: Optional[str] = Field(None, alias="BINANCE_API_SECRET")
    
    # Polymarket
    polymarket_api_url: str = Field("https://clob.polymarket.com", alias="POLYMARKET_API_URL")
    polygon_chain_id: int = Field(137, alias="POLYGON_CHAIN_ID")
    
    # Trading Config
    initial_bankroll: float = Field(100.0, alias="INITIAL_BANKROLL")
    max_bet_percent: float = Field(20.0, alias="MAX_BET_PERCENT")  # Aggressive for 5m
    max_concurrent_positions: int = Field(10, alias="MAX_CONCURRENT_POSITIONS")  # High volume
    min_edge: float = Field(2.0, alias="MIN_EDGE")  # Lower edge, higher volume
    
    # Speed Optimization
    max_latency_ms: int = Field(100, alias="MAX_LATENCY_MS")  # Skip if too slow
    
    # Dashboard
    dashboard_update_interval_ms: int = Field(500, alias="DASHBOARD_UPDATE_INTERVAL_MS")
    
    # Monitoring
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    sentry_dsn: Optional[str] = Field(None, alias="SENTRY_DSN")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
