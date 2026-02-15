"""Configuration for BTC 5m speed bot."""
from typing import Optional
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

# Find .env file (in project root, parent of src/)
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    """Settings from environment variables."""
    
    # Environment
    environment: str = Field("paper", alias="ENVIRONMENT")  # paper or live
    
    # Polygon Wallet
    polygon_wallet_private_key: str = Field(..., alias="POLYGON_WALLET_PRIVATE_KEY")
    polymarket_funder_address: Optional[str] = Field(None, alias="POLYMARKET_FUNDER_ADDRESS")
    
    # Anthropic (optional - for market analysis)
    anthropic_api_key: Optional[str] = Field(None, alias="ANTHROPIC_API_KEY")
    
    # Telegram (optional - dashboard-only mode if not set)
    telegram_bot_token: Optional[str] = Field(None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(None, alias="TELEGRAM_CHAT_ID")
    
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
    
    # Kelly Criterion Position Sizing
    kelly_fraction: float = Field(0.5, alias="KELLY_FRACTION")  # 0.5 = half-Kelly (recommended for reduced volatility)
    
    # Speed Optimization
    max_latency_ms: int = Field(100, alias="MAX_LATENCY_MS")  # Skip if too slow
    
    # Dashboard
    dashboard_update_interval_ms: int = Field(500, alias="DASHBOARD_UPDATE_INTERVAL_MS")
    
    # Monitoring
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    sentry_dsn: Optional[str] = Field(None, alias="SENTRY_DSN")
    
    class Config:
        env_file = _ENV_FILE
        case_sensitive = False


settings = Settings()


class ConfigWrapper:
    """Wrapper to provide both lowercase and uppercase access."""
    
    # Alias mappings for backward compatibility
    _ALIASES = {
        'polymarket_private_key': 'polygon_wallet_private_key',
        'polymarket_host': 'polymarket_api_url',
    }
    
    def __init__(self, settings):
        self._settings = settings
    
    def __getattr__(self, name):
        # Convert to lowercase for lookup
        lower = name.lower()
        
        # Check aliases first
        if lower in self._ALIASES:
            return getattr(self._settings, self._ALIASES[lower])
        
        # Try lowercase
        if hasattr(self._settings, lower):
            return getattr(self._settings, lower)
        
        # Try as-is
        if hasattr(self._settings, name):
            return getattr(self._settings, name)
        
        raise AttributeError(f"Config has no attribute '{name}'")


config = ConfigWrapper(settings)
