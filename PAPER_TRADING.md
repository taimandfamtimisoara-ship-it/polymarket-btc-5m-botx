# Paper Trading System - BTC 5m Bot

## Overview

The paper trading system allows you to run the bot in **observation mode** for 24 hours (or longer), connecting to real Polymarket data but **NOT trading real money**.

Instead, it:
- Records every trade decision with full context
- Tracks simulated positions
- Monitors real market outcomes
- Calculates what P&L WOULD have been
- Sends detailed Telegram reports
- Teaches the survival brain without risking capital

## Setup

### 1. Enable Paper Trading Mode

In your `.env` file:

```bash
ENVIRONMENT=paper
```

### 2. Start the Bot

```bash
cd src/
python main.py
```

The bot will start in observation mode and send a Telegram alert:

```
🚀 BTC 5m Bot Started

Mode: PAPER (Observation Mode)
BTC Price: $97,234.00
Feed: ✅ Connected

📊 Paper Trading Active
• Tracking all decisions
• Simulating positions
• No real money at risk
• Initial capital: $100.00
```

## What Gets Tracked

### Every Trade Decision

When an edge is detected and would have been traded:

```
📊 PAPER TRADE — BTC 5min

Would BUY YES at 0.42 (edge: 8.2%)

Reasoning:
• BTC at $97,234 — market implies $96,800 strike
• RSI: 65 (neutral) | MACD: bullish
• Survival state: HEALTHY (1.0x Kelly)
• Simulated size: $12.50 (12.5% of bankroll)

Tracking for resolution...
PAPER_20260215_0001
```

### Trade Resolutions

When markets resolve (after 5 minutes):

```
✅ PAPER TRADE RESOLVED — WIN

Entry: YES @ 0.42 | Exit: 1.00 (YES won)
Simulated P&L: +$7.25 (+58%)

Running totals:
• Paper P&L: +$23.40
• Win rate: 7/10 (70%)
• Survival state: THRIVING

PAPER_20260215_0001
```

### Daily Summary

At shutdown or on demand:

```
📈 24-HOUR PAPER TRADING SUMMARY

Total trades: 47
Wins: 31 | Losses: 16
Win rate: 66%

Simulated P&L: +$34.20
Starting capital: $100
Ending capital: $134.20 (+34.2%)

Survival brain journey:
• HEALTHY → WOUNDED (hour 8, 4 losses in a row)
• WOUNDED → HEALTHY (hour 14, recovered)
• HEALTHY → THRIVING (hour 20)

Best edge bucket: 5-10% (78% win rate)
Best hour: 14:00-15:00 UTC (5 wins, 1 loss)

Recommendation: Ready for live trading ✅
```

## Data Persistence

All paper trades are saved to disk for analysis:

### Trade Log
```
data/paper_trading/paper_trades.json
```

Contains all pending and completed trades with full context.

### Daily Summaries
```
data/paper_trading/paper_summaries/YYYY-MM-DD.json
```

End-of-day summary with complete statistics and all trades.

## Integration with Survival Brain

The paper trader **feeds simulated results to the survival brain**, so it learns patterns without risking real money:

- Win/loss tracking
- Pattern recognition (edge buckets, hourly performance)
- State transitions (HEALTHY → WOUNDED → THRIVING)
- Kelly sizing adjustments
- Edge threshold adjustments

This means when you switch to live mode, the survival brain will already have learned from the paper trading session.

## How It Works

### 1. Edge Detection
The bot runs the normal edge detection cycle, scanning Polymarket markets for opportunities.

### 2. Trade Decision
When an edge is detected:
- Survival brain checks if trade should be taken (edge threshold, pattern filtering)
- If approved, paper trader records the decision
- Position size is calculated using Kelly criterion + survival modifiers
- Telegram alert is sent with full reasoning

### 3. Resolution Tracking
Every 30 seconds, the paper trader checks if any pending trades have resolved:
- Markets older than 5 minutes are checked for outcomes
- P&L is calculated based on actual market resolution
- Survival brain is updated with the result
- Telegram alert is sent with outcome

### 4. Statistical Analysis
The paper trader tracks:
- **Win rate** by edge bucket (0-2%, 2-5%, 5-10%, 10%+)
- **Performance** by hour of day (0-23)
- **Survival state transitions** (when capital drops/rises)
- **Best/worst trades** (largest wins/losses)

## Command Reference

### Manual Daily Summary

If you want to check progress before 24 hours:

```python
# In Python REPL or script
from paper_trader import PaperTrader
import asyncio

# Load existing paper trader state
pt = PaperTrader(survival_brain, telegram_alerter, initial_capital=100)
asyncio.run(pt.send_daily_summary())
```

### Export Statistics

```python
stats = bot.paper_trader.get_stats()
print(json.dumps(stats, indent=2))
```

## Switching to Live Trading

Once you're satisfied with paper trading results:

1. **Review the daily summary**
   - Win rate ≥ 60%?
   - Positive P&L?
   - Survival brain stable?

2. **Update `.env`**
   ```bash
   ENVIRONMENT=live
   ```

3. **Restart the bot**
   ```bash
   python main.py
   ```

The survival brain will **retain all learned patterns** from paper trading.

## Important Notes

### Simulated Resolutions
Currently, the paper trader uses **simulated resolutions** based on edge probability. This is for testing purposes.

In production, you should integrate with the actual Polymarket resolution API to check real outcomes.

### Capital Tracking
Paper trading capital is **separate** from the survival brain's live capital tracking. The survival brain uses paper results for pattern learning but doesn't update its actual capital until you switch to live mode.

### Position Limits
Paper trading respects the same position sizing and Kelly limits as live trading, so you get realistic position sizes.

### Rate Limiting
Telegram alerts are rate-limited to prevent spam:
- Trade alerts: 1 per 10 seconds
- Resolution alerts: 1 per 10 seconds
- Daily summary: Always sent (no rate limit)

## Troubleshooting

### No trades being recorded

Check:
1. Is `ENVIRONMENT=paper` in `.env`?
2. Are edges being detected? (Check logs)
3. Is survival brain rejecting trades? (Check `min_edge_threshold`)

### Trades not resolving

Check:
1. Are markets old enough? (5+ minutes)
2. Is resolution check running? (Every 30 seconds)
3. Check logs for `paper_resolution_check_failed`

### No Telegram alerts

Check:
1. `TELEGRAM_BOT_TOKEN` configured?
2. `TELEGRAM_CHAT_ID` configured?
3. Rate limiting? (Wait 10 seconds between same alert types)

## Files Modified

- `src/paper_trader.py` — New paper trading system
- `src/main.py` — Integrated paper trader into bot lifecycle
- `PAPER_TRADING.md` — This documentation

## Next Steps

After successful paper trading:

1. **Analyze patterns** — Which edge buckets perform best?
2. **Tune parameters** — Adjust `MIN_EDGE`, `MAX_BET_PERCENT`, etc.
3. **Review survival states** — Did the bot handle drawdowns well?
4. **Switch to live** — When confident, enable live trading

---

**Remember:** Paper trading is observation mode. It teaches the bot what works without risking real money. Use it before going live.
