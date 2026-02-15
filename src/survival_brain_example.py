"""
Example integration of SurvivalBrain into the main trading loop.

This shows how to connect the survival brain to your edge detector,
execution engine, and dashboard.
"""

import asyncio
from datetime import datetime
from survival_brain import SurvivalBrain
from telegram_alerts import TelegramAlerter
from config import settings


async def main():
    """Example main loop with survival brain integration."""
    
    # Initialize components
    telegram_alerter = TelegramAlerter(
        token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id
    )
    
    survival_brain = SurvivalBrain(
        initial_capital=settings.initial_bankroll,
        telegram_alerter=telegram_alerter,
        data_dir="data/survival"
    )
    
    print("🧠 Survival Brain initialized")
    print(f"Initial capital: ${survival_brain.initial_capital:.2f}")
    print(f"Current state: {survival_brain.current_state.value}")
    
    # Main trading loop
    while True:
        try:
            # 1. Get survival status (for logging/dashboard)
            status = survival_brain.get_survival_status()
            print(f"\n📊 Status: {status.state.value} | Capital: ${status.current_capital:.2f} ({status.capital_pct:.1f}%)")
            
            # 2. Check if we should halt (DEAD state)
            if status.state.value == "DEAD":
                print("☠️ DEAD state — Trading halted. Waiting for Basel's guidance.")
                await asyncio.sleep(60)
                continue
            
            # 3. Detect edge opportunities (your edge detector)
            # edge_opportunity = await edge_detector.find_opportunities()
            
            # Example edge opportunity:
            edge_opportunity = {
                'edge': 4.5,  # 4.5% edge
                'market_type': 'btc_price',
                'market_id': 'example_market_123',
                'probability': 0.55,
                'price': 0.50
            }
            
            # 4. Ask survival brain if we should take this trade
            should_take, reason = survival_brain.should_take_trade(
                edge=edge_opportunity['edge'],
                market_type=edge_opportunity['market_type'],
                hour=datetime.now().hour
            )
            
            if not should_take:
                print(f"❌ Trade rejected: {reason}")
                await asyncio.sleep(10)
                continue
            
            print(f"✅ Trade approved: {reason}")
            
            # 5. Get position sizing modifier
            kelly_modifier = survival_brain.get_position_size_modifier()
            
            # Calculate position size with survival brain modifier
            base_kelly_size = 100.0  # Your base Kelly calculation
            adjusted_size = base_kelly_size * kelly_modifier
            
            print(f"💰 Position size: ${adjusted_size:.2f} (Kelly modifier: {kelly_modifier:.2f}x)")
            
            # 6. Execute trade (your execution engine)
            # trade_result = await execution_engine.place_order(...)
            
            # Example trade result:
            trade_result = {
                'pnl': 2.5,  # Won $2.50
                'edge': edge_opportunity['edge'],
                'market_type': edge_opportunity['market_type'],
                'timestamp': datetime.now(),
                'won': True
            }
            
            # 7. Record trade result
            survival_brain.record_trade_result(trade_result)
            
            print(f"📝 Trade recorded: PnL ${trade_result['pnl']:.2f}")
            
            # 8. Periodic survival brain tick (checks milestones, state transitions, etc.)
            await survival_brain.tick()
            
            # 9. Send daily report (at end of day)
            current_hour = datetime.now().hour
            if current_hour == 23:  # 11 PM
                await survival_brain.send_daily_survival_report()
            
            # Wait before next opportunity
            await asyncio.sleep(30)
            
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
