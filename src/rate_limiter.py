"""Token bucket rate limiter with async support and 429 backoff."""
import asyncio
import structlog
import time
from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import deque

logger = structlog.get_logger()


class TokenBucket:
    """
    Token bucket algorithm for rate limiting.
    
    Features:
    - Configurable requests per second
    - Burst capacity for spikes
    - Non-blocking async implementation
    - Zero latency when under limit
    - Automatic token refill
    """
    
    def __init__(
        self,
        rate: float,
        capacity: Optional[int] = None,
        name: str = "default"
    ):
        """
        Initialize token bucket.
        
        Args:
            rate: Requests per second (e.g., 1.0 = 1 req/sec, 0.167 = 10 req/min)
            capacity: Bucket capacity (max burst). Defaults to rate * 2
            name: Bucket name for logging
        """
        self.rate = rate  # Tokens added per second
        self.capacity = capacity or max(int(rate * 2), 1)
        self.name = name
        
        # Current tokens available
        self.tokens = float(self.capacity)
        
        # Last refill timestamp
        self.last_refill = time.monotonic()
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
        
        # Stats
        self.total_requests = 0
        self.total_waits = 0
        self.total_wait_time_ms = 0.0
        
        logger.info(
            "rate_limiter_initialized",
            name=name,
            rate_per_sec=rate,
            capacity=self.capacity
        )
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        
        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.rate
        self.tokens = min(self.tokens + tokens_to_add, self.capacity)
        
        self.last_refill = now
    
    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens from bucket (async, non-blocking when available).
        
        Args:
            tokens: Number of tokens to acquire (default: 1)
        
        Returns:
            Wait time in milliseconds (0 if no wait)
        """
        async with self._lock:
            self._refill()
            
            self.total_requests += 1
            
            # If we have enough tokens, grant immediately
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0
            
            # Calculate wait time needed
            tokens_needed = tokens - self.tokens
            wait_seconds = tokens_needed / self.rate
            
            # Track wait stats
            self.total_waits += 1
            wait_ms = wait_seconds * 1000
            self.total_wait_time_ms += wait_ms
            
            logger.debug(
                "rate_limit_wait",
                name=self.name,
                tokens_needed=round(tokens_needed, 2),
                wait_ms=round(wait_ms, 1)
            )
            
            # Wait for tokens to refill
            await asyncio.sleep(wait_seconds)
            
            # Refill and deduct tokens
            self._refill()
            self.tokens -= tokens
            
            return wait_ms
    
    def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting (synchronous check).
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            True if acquired, False if would need to wait
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False
    
    def get_stats(self) -> Dict:
        """Get bucket statistics."""
        avg_wait_ms = (
            self.total_wait_time_ms / self.total_waits
            if self.total_waits > 0
            else 0.0
        )
        
        wait_rate = (
            (self.total_waits / self.total_requests) * 100
            if self.total_requests > 0
            else 0.0
        )
        
        return {
            'name': self.name,
            'rate_per_sec': self.rate,
            'capacity': self.capacity,
            'current_tokens': round(self.tokens, 2),
            'total_requests': self.total_requests,
            'total_waits': self.total_waits,
            'wait_rate_pct': round(wait_rate, 2),
            'avg_wait_ms': round(avg_wait_ms, 2),
            'total_wait_time_ms': round(self.total_wait_time_ms, 2)
        }


class RateLimiter:
    """
    Multi-bucket rate limiter with 429 backoff handling.
    
    Manages separate rate limits for:
    - Market fetching
    - Price fetching
    - Order submission
    """
    
    def __init__(self):
        """Initialize rate limiter with default buckets."""
        # Market fetching: 10 requests per minute
        self.market_bucket = TokenBucket(
            rate=10 / 60,  # 0.167 req/sec
            capacity=5,  # Allow 5-request burst
            name="market_fetch"
        )
        
        # Price fetching: 60 requests per minute
        self.price_bucket = TokenBucket(
            rate=60 / 60,  # 1.0 req/sec
            capacity=10,  # Allow 10-request burst
            name="price_fetch"
        )
        
        # Order submission: 30 requests per minute
        self.order_bucket = TokenBucket(
            rate=30 / 60,  # 0.5 req/sec
            capacity=5,  # Allow 5-request burst
            name="order_submit"
        )
        
        # 429 backoff state
        self._backoff_until: Optional[datetime] = None
        self._backoff_duration_ms = 1000  # Start at 1 second
        self._max_backoff_ms = 60000  # Max 60 seconds
        self._429_count = 0
        
        # Track 429 responses over time
        self._429_history = deque(maxlen=100)
        
        logger.info("rate_limiter_ready", buckets=3)
    
    async def acquire_market(self) -> float:
        """
        Acquire token for market fetching.
        
        Returns:
            Wait time in milliseconds
        """
        await self._check_backoff()
        return await self.market_bucket.acquire()
    
    async def acquire_price(self) -> float:
        """
        Acquire token for price fetching.
        
        Returns:
            Wait time in milliseconds
        """
        await self._check_backoff()
        return await self.price_bucket.acquire()
    
    async def acquire_order(self) -> float:
        """
        Acquire token for order submission.
        
        Returns:
            Wait time in milliseconds
        """
        await self._check_backoff()
        return await self.order_bucket.acquire()
    
    async def _check_backoff(self):
        """Check if we're in backoff period and wait if needed."""
        if self._backoff_until and datetime.now() < self._backoff_until:
            wait_seconds = (self._backoff_until - datetime.now()).total_seconds()
            
            logger.warning(
                "rate_limit_backoff_active",
                wait_seconds=round(wait_seconds, 1),
                backoff_duration_ms=self._backoff_duration_ms,
                total_429s=self._429_count
            )
            
            await asyncio.sleep(wait_seconds)
            
            # Clear backoff after waiting
            self._backoff_until = None
    
    def handle_429(self, endpoint: str = "unknown"):
        """
        Handle 429 Too Many Requests response with exponential backoff.
        
        Args:
            endpoint: Which endpoint returned 429 (for logging)
        """
        self._429_count += 1
        self._429_history.append({
            'timestamp': datetime.now(),
            'endpoint': endpoint,
            'backoff_ms': self._backoff_duration_ms
        })
        
        # Set backoff period
        self._backoff_until = datetime.now() + timedelta(
            milliseconds=self._backoff_duration_ms
        )
        
        logger.warning(
            "rate_limit_429_detected",
            endpoint=endpoint,
            backoff_ms=self._backoff_duration_ms,
            total_429s=self._429_count,
            backoff_until=self._backoff_until.isoformat()
        )
        
        # Exponential backoff (double the duration)
        self._backoff_duration_ms = min(
            self._backoff_duration_ms * 2,
            self._max_backoff_ms
        )
    
    def reset_backoff(self):
        """Reset backoff state after successful requests."""
        if self._backoff_duration_ms > 1000:
            # Gradually reduce backoff on success
            self._backoff_duration_ms = max(
                self._backoff_duration_ms // 2,
                1000
            )
    
    def get_stats(self) -> Dict:
        """Get comprehensive rate limiter statistics."""
        # Recent 429s (last 5 minutes)
        five_min_ago = datetime.now() - timedelta(minutes=5)
        recent_429s = sum(
            1 for h in self._429_history
            if h['timestamp'] > five_min_ago
        )
        
        return {
            'buckets': {
                'market': self.market_bucket.get_stats(),
                'price': self.price_bucket.get_stats(),
                'order': self.order_bucket.get_stats()
            },
            'backoff': {
                'active': self._backoff_until is not None,
                'until': self._backoff_until.isoformat() if self._backoff_until else None,
                'duration_ms': self._backoff_duration_ms,
                'total_429s': self._429_count,
                'recent_429s_5min': recent_429s
            }
        }
    
    def is_throttled(self) -> bool:
        """Check if currently in backoff period."""
        return self._backoff_until is not None and datetime.now() < self._backoff_until


# Global instance
rate_limiter: Optional[RateLimiter] = None


def init_rate_limiter() -> RateLimiter:
    """Initialize global rate limiter instance."""
    global rate_limiter
    rate_limiter = RateLimiter()
    logger.info("global_rate_limiter_initialized")
    return rate_limiter


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance (initializes if needed)."""
    global rate_limiter
    if rate_limiter is None:
        rate_limiter = init_rate_limiter()
    return rate_limiter
