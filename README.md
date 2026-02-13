# ⚡ BTC 5-Minute Trading Bot

**Ultra-fast Polymarket bot for 5-minute BTC markets.**

Capitalizes on the new 5-minute Polymarket markets by:
1. Streaming real-time BTC prices via WebSocket (<50ms latency)
2. Comparing real price movements vs market odds
3. Executing profitable opportunities in <100ms

## Architecture

```
BTC Price Feed (Binance WebSocket)
    ↓
Edge Detector (Price vs Odds)
    ↓
Execution Engine (Fast Orders)
    ↓
Real-time Dashboard (500ms updates)
```

## Features

- **WebSocket price feeds** — <50ms latency from Binance
- **Simple edge detection** — Real price vs market odds comparison
- **Speed-optimized execution** — Target <100ms from edge to order
- **Real-time dashboard** — 500ms update interval
- **Paper trading mode** — Test strategies risk-free
- **Aggressive config** — 20% max bet, 10 concurrent positions

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

Required env vars:
- `POLYMARKET_PRIVATE_KEY` — Your Polygon wallet private key
- `ENVIRONMENT` — `paper` or `live`

### 3. Run Bot

```bash
# Paper trading (no real money)
python src/main.py

# Live trading (REAL MONEY)
ENVIRONMENT=live python src/main.py
```

### 4. Run Dashboard (optional)

In separate terminal:

```bash
cd src
uvicorn dashboard_api:app --reload --port 8000
```

Then open `dashboard/index.html` in browser.

## Configuration

Edit `src/config.py` or use environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_BET_PCT` | 20 | Max % of balance per trade |
| `MAX_CONCURRENT_POSITIONS` | 10 | Max open positions |
| `MIN_EDGE_PCT` | 2 | Minimum edge to trade |
| `MAX_LATENCY_MS` | 100 | Max feed latency |

## Strategy

**Core Logic:**
1. Get real-time BTC price from Binance
2. Compare to Polymarket 5-minute market odds
3. If real movement > implied movement → Edge detected
4. Execute fast (milliseconds matter)

**Example:**
- BTC moved +0.5% in last minute
- Market shows YES at 0.45 (implying +5% move)
- Edge = real > market → BET YES
- Execute in <100ms before others catch up

## Deployment

### Railway (Bot)

1. Create new Railway project
2. Connect GitHub repo
3. Add environment variables (no `POLYMARKET_PRIVATE_KEY` in code!)
4. Deploy

### Vercel (Dashboard - Optional)

1. Deploy `dashboard/` folder to Vercel
2. Update `API_URL` in `index.html` to Railway URL
3. Done

## File Structure

```
btc-5m-bot/
├── src/
│   ├── main.py              # Main orchestrator
│   ├── config.py            # Configuration
│   ├── price_feed.py        # BTC WebSocket feed
│   ├── edge_detector.py     # Edge detection logic
│   ├── execution_engine.py  # Order execution
│   ├── market_fetcher.py    # Fetch Polymarket markets
│   └── dashboard_api.py     # Dashboard API
├── dashboard/
│   └── index.html           # Real-time dashboard
├── requirements.txt         # Python dependencies
├── Dockerfile              # Railway deployment
├── railway.json            # Railway config
└── README.md               # This file
```

## Performance Targets

- **Price feed latency:** <50ms
- **Edge to execution:** <100ms
- **Dashboard updates:** 500ms
- **Cycle time:** <50ms (when no orders)

## Safety

**PAPER MODE BY DEFAULT**
- Set `ENVIRONMENT=live` only when ready
- Start with small amounts
- Monitor closely
- 5-minute markets = HIGH RISK

**Never commit:**
- Private keys
- `.env` files
- Wallet addresses

## Monitoring

Dashboard shows:
- Current BTC price
- Feed latency
- Active positions
- Edges detected
- Orders executed
- Average execution time

## Logs

Structured JSON logs via `structlog`:
```json
{
  "event": "edge_detected",
  "direction": "YES",
  "edge_pct": 3.5,
  "btc_price": 95234.12,
  "timestamp": "2024-02-13T10:30:45.123Z"
}
```

## Troubleshooting

**WebSocket disconnects**
- Auto-reconnects after 1 second
- Check internet connection

**No markets found**
- 5-minute markets may not be live yet
- Check Polymarket website

**High latency**
- Bot pauses trading if latency > 100ms
- Check network connection

## Future Improvements

- [ ] Track price history for better edge detection
- [ ] Add technical indicators (RSI, MACD)
- [ ] Multi-exchange price feeds (redundancy)
- [ ] Telegram alerts for large edges
- [ ] Advanced position sizing (Kelly Criterion)
- [ ] Auto-close positions near market end

## Risk Disclaimer

**THIS BOT TRADES REAL MONEY ON POLYMARKET**

- 5-minute markets = extreme volatility
- You can lose your entire stake
- Test thoroughly in paper mode first
- Start with small amounts
- No guarantees of profit
- Use at your own risk

## License

MIT

## Support

Questions? Check:
- Polymarket docs: https://docs.polymarket.com
- py-clob-client: https://github.com/Polymarket/py-clob-client

---

**Built for speed. Optimized for opportunity.**

⚡ First to detect. First to execute. First to profit.
