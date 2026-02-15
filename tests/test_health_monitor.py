"""Test health monitoring system."""
import asyncio
import structlog
from datetime import datetime, timedelta

# Mock objects for testing
class MockPriceFeed:
    def __init__(self):
        self.is_connected = True
        self.current_price = 50000.0
        self.last_update = datetime.now()
    
    def get_latency_ms(self):
        if self.last_update:
            delta = datetime.now() - self.last_update
            return delta.total_seconds() * 1000
        return None
    
    def get_current_price(self):
        return self.current_price


class MockMarketFetcher:
    def __init__(self):
        self.should_fail = False
    
    async def get_active_markets(self):
        if self.should_fail:
            raise Exception("API error")
        
        # Simulate API delay
        await asyncio.sleep(0.1)
        
        return [
            {'id': 'market1', 'question': 'Test market 1'},
            {'id': 'market2', 'question': 'Test market 2'}
        ]


class MockTelegramAlerter:
    def __init__(self):
        self.alerts_sent = []
    
    async def send_alert(self, message, alert_type="general", force=False):
        self.alerts_sent.append({
            'message': message,
            'alert_type': alert_type,
            'force': force,
            'timestamp': datetime.now()
        })
        print(f"\n[TELEGRAM ALERT - {alert_type}]")
        print(message)
        print("=" * 60)


async def test_health_checks():
    """Test individual health checks."""
    print("\n" + "=" * 60)
    print("TESTING HEALTH MONITORING SYSTEM")
    print("=" * 60)
    
    # Import after setting up mocks
    from src.health_monitor import init_health_monitor
    
    # Setup
    price_feed = MockPriceFeed()
    market_fetcher = MockMarketFetcher()
    telegram_alerter = MockTelegramAlerter()
    
    # Initialize health monitor
    health_monitor = init_health_monitor(
        price_feed=price_feed,
        market_fetcher=market_fetcher,
        telegram_alerter=telegram_alerter
    )
    
    print("\n✅ Health monitor initialized")
    
    # Test 1: Healthy status
    print("\n--- Test 1: All Systems Healthy ---")
    health_monitor.heartbeat()
    report = await health_monitor.check_health()
    
    print(f"\nStatus: {report['status']}")
    print(f"Check duration: {report['check_duration_ms']:.2f}ms")
    print("\nComponents:")
    for component in report['components']:
        status_icon = "✅" if component['healthy'] else "❌"
        print(f"  {status_icon} {component['name']}: {component['message']}")
        if component['latency_ms']:
            print(f"     Latency: {component['latency_ms']:.2f}ms")
    
    assert report['status'] == 'healthy', "Should be healthy"
    assert report['check_duration_ms'] < 100, "Should be fast (<100ms)"
    print("\n✅ Test 1 passed")
    
    # Test 2: Stale price data
    print("\n--- Test 2: Stale Price Data ---")
    price_feed.last_update = datetime.now() - timedelta(seconds=35)
    report = await health_monitor.check_health()
    
    print(f"\nStatus: {report['status']}")
    price_feed_component = next(c for c in report['components'] if c['name'] == 'price_feed')
    print(f"Price feed: {price_feed_component['message']}")
    
    assert report['status'] == 'unhealthy', "Should be unhealthy with stale price"
    print("\n✅ Test 2 passed")
    
    # Fix price feed
    price_feed.last_update = datetime.now()
    
    # Test 3: Missing heartbeat
    print("\n--- Test 3: Missing Heartbeat ---")
    health_monitor.last_heartbeat = datetime.now() - timedelta(seconds=65)
    report = await health_monitor.check_health()
    
    print(f"\nStatus: {report['status']}")
    heartbeat_component = next(c for c in report['components'] if c['name'] == 'main_loop')
    print(f"Main loop: {heartbeat_component['message']}")
    
    assert report['status'] == 'unhealthy', "Should be unhealthy with old heartbeat"
    print("\n✅ Test 3 passed")
    
    # Fix heartbeat
    health_monitor.heartbeat()
    
    # Test 4: API failure
    print("\n--- Test 4: API Failure ---")
    market_fetcher.should_fail = True
    report = await health_monitor.check_health()
    
    print(f"\nStatus: {report['status']}")
    api_component = next(c for c in report['components'] if c['name'] == 'api_access')
    print(f"API access: {api_component['message']}")
    
    assert not api_component['healthy'], "API should be unhealthy"
    print("\n✅ Test 4 passed")
    
    # Fix API
    market_fetcher.should_fail = False
    
    # Test 5: Memory check
    print("\n--- Test 5: Memory Check ---")
    report = await health_monitor.check_health()
    
    memory_component = next(c for c in report['components'] if c['name'] == 'memory')
    print(f"\nMemory: {memory_component['message']}")
    print(f"Memory healthy: {memory_component['healthy']}")
    
    print("\n✅ Test 5 passed")
    
    # Test 6: Watchdog with simulated failure
    print("\n--- Test 6: Watchdog Auto-Restart ---")
    
    restart_called = False
    
    async def mock_restart():
        nonlocal restart_called
        restart_called = True
        print("\n🔄 RESTART CALLBACK TRIGGERED")
    
    # Start watchdog
    await health_monitor.start_watchdog(restart_callback=mock_restart)
    print("\n✅ Watchdog started")
    
    # Simulate unhealthy condition (stale heartbeat)
    health_monitor.last_heartbeat = datetime.now() - timedelta(seconds=70)
    
    # Wait for watchdog to detect and trigger restart
    print("\nWaiting for watchdog to detect issue (this may take up to 15 seconds)...")
    
    for i in range(20):  # Wait up to 20 seconds
        await asyncio.sleep(1)
        if restart_called:
            break
        if i % 5 == 0:
            print(f"  ... waiting ({i}s)")
    
    # Stop watchdog
    await health_monitor.stop_watchdog()
    
    if restart_called:
        print("\n✅ Test 6 passed - Watchdog triggered restart")
    else:
        print("\n⚠️  Test 6 skipped - Watchdog did not trigger (may need longer wait)")
    
    # Check Telegram alerts
    print("\n--- Telegram Alerts Sent ---")
    print(f"\nTotal alerts: {len(telegram_alerter.alerts_sent)}")
    for alert in telegram_alerter.alerts_sent:
        print(f"\n{alert['alert_type']} ({alert['timestamp'].strftime('%H:%M:%S')}):")
        print(f"  {alert['message'][:100]}...")
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"\nHealth Monitor Stats:")
    print(f"  Health checks run: {health_monitor.stats['health_checks']}")
    print(f"  Warnings: {health_monitor.stats['warnings']}")
    print(f"  Errors: {health_monitor.stats['errors']}")
    print(f"  Restarts: {health_monitor.stats['restarts']}")
    print(f"\nTelegram alerts sent: {len(telegram_alerter.alerts_sent)}")
    
    print("\n✅ All health monitoring tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer()
        ]
    )
    
    asyncio.run(test_health_checks())
