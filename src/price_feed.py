"""Real-time BTC price feed via WebSocket - OPTIMIZED FOR SPEED."""
import asyncio
import json
from typing import Optional, Callable
from datetime import datetime
import structlog
import websockets

logger = structlog.get_logger()


class BTCPriceFeed:
    """
    Ultra-fast BTC price feed.
    
    Uses Binance WebSocket for real-time prices.
    Latency: <50ms typical.
    """
    
    def __init__(self):
        self.current_price: Optional[float] = None
        self.last_update: Optional[datetime] = None
        self.ws = None
        self.callbacks = []
        self.is_connected = False
        
    async def connect(self):
        """Connect to Binance WebSocket."""
        try:
            # Binance WebSocket URL for BTC/USDT ticker
            url = "wss://stream.binance.com:9443/ws/btcusdt@ticker"
            
            self.ws = await websockets.connect(url)
            self.is_connected = True
            
            logger.info("price_feed_connected", source="binance")
            
            # Start listening
            asyncio.create_task(self._listen())
            
        except Exception as e:
            logger.error("price_feed_connection_failed", error=str(e))
            self.is_connected = False
    
    async def _listen(self):
        """Listen for price updates."""
        try:
            async for message in self.ws:
                data = json.loads(message)
                
                # Extract current price
                price = float(data['c'])  # 'c' = current price
                
                # Update
                old_price = self.current_price
                self.current_price = price
                self.last_update = datetime.now()
                
                # Calculate change
                if old_price:
                    change_pct = ((price - old_price) / old_price) * 100
                else:
                    change_pct = 0
                
                # Notify callbacks (for dashboard + trading engine)
                for callback in self.callbacks:
                    try:
                        await callback(price, change_pct)
                    except Exception as e:
                        logger.error("callback_failed", error=str(e))
                
        except Exception as e:
            logger.error("price_feed_error", error=str(e))
            self.is_connected = False
            
            # Reconnect
            await asyncio.sleep(1)
            await self.connect()
    
    def register_callback(self, callback: Callable):
        """Register a callback for price updates."""
        self.callbacks.append(callback)
    
    def get_current_price(self) -> Optional[float]:
        """Get current BTC price."""
        return self.current_price
    
    def get_latency_ms(self) -> Optional[float]:
        """Get feed latency in milliseconds."""
        if not self.last_update:
            return None
        
        delta = datetime.now() - self.last_update
        return delta.total_seconds() * 1000
    
    async def close(self):
        """Close WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.is_connected = False


# Singleton instance
price_feed = BTCPriceFeed()
