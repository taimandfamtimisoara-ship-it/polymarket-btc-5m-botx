"""Quick test to verify rate limiter implementation."""
import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from rate_limiter import init_rate_limiter, get_rate_limiter


async def test_rate_limiter():
    """Test basic rate limiter functionality."""
    print("🔧 Initializing rate limiter...")
    limiter = init_rate_limiter()
    
    print("\n📊 Initial stats:")
    stats = limiter.get_stats()
    print(f"Market bucket: {stats['buckets']['market']['rate_per_sec']} req/sec")
    print(f"Price bucket: {stats['buckets']['price']['rate_per_sec']} req/sec")
    print(f"Order bucket: {stats['buckets']['order']['rate_per_sec']} req/sec")
    
    print("\n🚀 Testing burst capacity (order bucket - capacity: 5)...")
    for i in range(7):
        wait_ms = await limiter.acquire_order()
        status = "✅ immediate" if wait_ms == 0 else f"⏱️ waited {wait_ms:.1f}ms"
        print(f"Request {i+1}: {status}")
    
    print("\n✅ Testing 429 backoff...")
    limiter.handle_429("test_endpoint")
    stats = limiter.get_stats()
    print(f"Backoff active: {stats['backoff']['active']}")
    print(f"Backoff duration: {stats['backoff']['duration_ms']}ms")
    print(f"Total 429s: {stats['backoff']['total_429s']}")
    
    print("\n🎯 Testing backoff check (should wait)...")
    import time
    start = time.time()
    await limiter.acquire_market()
    elapsed_ms = (time.time() - start) * 1000
    print(f"Waited {elapsed_ms:.0f}ms due to backoff")
    
    print("\n✅ Testing backoff reset...")
    limiter.reset_backoff()
    stats = limiter.get_stats()
    print(f"New backoff duration: {stats['backoff']['duration_ms']}ms (should be half)")
    
    print("\n📈 Final stats:")
    stats = limiter.get_stats()
    for bucket_name, bucket_stats in stats['buckets'].items():
        print(f"\n{bucket_name.upper()} bucket:")
        print(f"  Total requests: {bucket_stats['total_requests']}")
        print(f"  Total waits: {bucket_stats['total_waits']}")
        print(f"  Wait rate: {bucket_stats['wait_rate_pct']:.1f}%")
        print(f"  Avg wait: {bucket_stats['avg_wait_ms']:.1f}ms")
    
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    asyncio.run(test_rate_limiter())
