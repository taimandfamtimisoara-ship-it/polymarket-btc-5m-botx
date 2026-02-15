"""Real-time BTC price feed via WebSocket - OPTIMIZED FOR SPEED."""
import asyncio
import json
from typing import Optional, Callable, List
from datetime import datetime
from collections import deque
import structlog
import websockets
import aiohttp

logger = structlog.get_logger()


class BTCPriceFeed:
    """
    Ultra-fast BTC price feed.
    
    Uses Binance WebSocket for real-time prices.
    Latency: <50ms typical.
    
    Tracks price history for momentum indicators (RSI, MACD).
    """
    
    def __init__(self, history_size: int = 50):
        self.current_price: Optional[float] = None
        self.last_update: Optional[datetime] = None
        self.ws = None
        self.callbacks = []
        self.is_connected = False
        
        # Price history for indicators (rolling window)
        self.price_history: deque = deque(maxlen=history_size)
        self.history_size = history_size
        
        # OPTIMIZATION: Latency tracking
        self.price_update_latency_ms: Optional[float] = None
        self.latency_history: deque = deque(maxlen=100)  # Track last 100 updates
        self.update_count = 0
        
    async def connect(self):
        """Connect to price feed. Try Binance WebSocket first, fallback to REST API."""
        # Try Binance WebSocket first
        try:
            url = "wss://stream.binance.com:9443/ws/btcusdt@ticker"
            self.ws = await asyncio.wait_for(websockets.connect(url), timeout=5)
            self.is_connected = True
            self._use_rest_fallback = False
            logger.info("price_feed_connected", source="binance_ws")
            asyncio.create_task(self._listen())
            return
        except Exception as e:
            logger.warning("binance_ws_failed", error=str(e))
        
        # Fallback to REST API polling (CoinGecko)
        logger.info("price_feed_using_rest_fallback", source="coingecko")
        self._use_rest_fallback = True
        self.is_connected = True
        asyncio.create_task(self._poll_rest_api())
    
    async def _poll_rest_api(self):
        """Fallback: Poll REST API for price updates."""
        async with aiohttp.ClientSession() as session:
            while self.is_connected:
                try:
                    # CoinGecko free API (no key needed)
                    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            price = float(data['bitcoin']['usd'])
                            
                            old_price = self.current_price
                            self.current_price = price
                            self.last_update = datetime.now()
                            self.price_history.append(price)
                            self.update_count += 1
                            
                            change_pct = ((price - old_price) / old_price * 100) if old_price else 0
                            
                            for callback in self.callbacks:
                                try:
                                    await callback(price, change_pct)
                                except Exception as e:
                                    logger.error("callback_failed", error=str(e))
                            
                            logger.debug("rest_price_update", price=price)
                        else:
                            logger.warning("rest_api_error", status=resp.status)
                except Exception as e:
                    logger.error("rest_poll_error", error=str(e))
                
                # Poll every 2 seconds (CoinGecko rate limit friendly)
                await asyncio.sleep(2)
    
    async def _listen(self):
        """Listen for price updates."""
        try:
            async for message in self.ws:
                # OPTIMIZATION: Track latency from message receipt
                receive_time = datetime.now()
                
                data = json.loads(message)
                
                # Extract current price and timestamp from exchange
                price = float(data['c'])  # 'c' = current price
                event_time = data.get('E', 0)  # Exchange timestamp (ms)
                
                # Update
                old_price = self.current_price
                self.current_price = price
                self.last_update = receive_time
                
                # OPTIMIZATION: Calculate actual latency from exchange
                if event_time:
                    exchange_time = datetime.fromtimestamp(event_time / 1000)
                    latency_ms = (receive_time - exchange_time).total_seconds() * 1000
                    self.price_update_latency_ms = latency_ms
                    self.latency_history.append(latency_ms)
                    
                    # Log high latency warnings
                    if latency_ms > 100:
                        logger.warning("high_price_feed_latency", latency_ms=round(latency_ms, 2))
                
                # Add to history
                self.price_history.append(price)
                self.update_count += 1
                
                # Calculate change
                if old_price:
                    change_pct = ((price - old_price) / old_price) * 100
                else:
                    change_pct = 0
                
                # Log periodic latency stats (every 100 updates)
                if self.update_count % 100 == 0 and self.latency_history:
                    avg_latency = sum(self.latency_history) / len(self.latency_history)
                    max_latency = max(self.latency_history)
                    logger.info(
                        "price_feed_latency_stats",
                        updates=self.update_count,
                        avg_latency_ms=round(avg_latency, 2),
                        max_latency_ms=round(max_latency, 2),
                        current_latency_ms=round(self.price_update_latency_ms, 2)
                    )
                
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
    
    def get_price_history(self) -> List[float]:
        """Get price history for indicator calculations."""
        return list(self.price_history)
    
    def get_latency_ms(self) -> Optional[float]:
        """
        Get feed latency in milliseconds.
        
        Returns time since last price update (staleness).
        For exchange latency, use get_price_update_latency_ms().
        """
        if not self.last_update:
            return None
        
        delta = datetime.now() - self.last_update
        return delta.total_seconds() * 1000
    
    def get_price_update_latency_ms(self) -> Optional[float]:
        """
        OPTIMIZATION: Get actual price update latency from exchange.
        
        This is the latency between when the exchange generated the price
        and when we received it via WebSocket.
        """
        return self.price_update_latency_ms
    
    def get_avg_latency_ms(self) -> Optional[float]:
        """Get average price update latency over recent history."""
        if not self.latency_history:
            return None
        return sum(self.latency_history) / len(self.latency_history)
    
    def get_latency_stats(self) -> dict:
        """Get comprehensive latency statistics."""
        if not self.latency_history:
            return {
                'current_ms': None,
                'avg_ms': None,
                'max_ms': None,
                'min_ms': None,
                'samples': 0
            }
        
        return {
            'current_ms': round(self.price_update_latency_ms, 2) if self.price_update_latency_ms else None,
            'avg_ms': round(sum(self.latency_history) / len(self.latency_history), 2),
            'max_ms': round(max(self.latency_history), 2),
            'min_ms': round(min(self.latency_history), 2),
            'samples': len(self.latency_history)
        }
    
    async def close(self):
        """Close WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.is_connected = False


# Singleton instance
price_feed = BTCPriceFeed()
