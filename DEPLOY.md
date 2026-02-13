# Deployment Guide — BTC 5-Minute Bot

**Two parts:**
1. Bot → Railway (backend)
2. Dashboard → Vercel (frontend, optional)

---

## Part 1: Deploy Bot to Railway

### 1. Prepare GitHub Repo

```bash
cd C:\Users\Administrator\Desktop\polymarket-bots\btc-5m-bot

# Initialize git (if not already)
git init

# Add files
git add .
git commit -m "Initial commit: BTC 5m bot"

# Push to GitHub
git remote add origin git@github.com:taimandfamtimisoara-ship-it/polymarket-btc-5m-bot.git
git branch -M main
git push -u origin main
```

### 2. Create Railway Project

1. Go to https://railway.app
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose `taimandfamtimisoara-ship-it/polymarket-btc-5m-bot`
5. Railway auto-detects Dockerfile ✓

### 3. Add Environment Variables

In Railway dashboard, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `ENVIRONMENT` | `paper` | Start with paper trading |
| `POLYMARKET_PRIVATE_KEY` | `your_key` | **NEVER commit this** |
| `POLYMARKET_HOST` | `https://clob.polymarket.com` | Production host |
| `MAX_BET_PCT` | `20` | Max 20% per trade |
| `MAX_CONCURRENT_POSITIONS` | `10` | Max 10 positions |
| `MIN_EDGE_PCT` | `2` | 2% minimum edge |
| `MAX_LATENCY_MS` | `100` | 100ms max latency |

### 4. Deploy

Railway auto-deploys on push.

Check logs:
```
✓ bot_initialized
✓ price_feed_connected
✓ bot_started mode=paper
```

### 5. Test Paper Trading

Let it run for 1-2 hours in paper mode.

Check logs for:
- `edge_detected` events
- `paper_trade` executions
- No errors

### 6. Switch to Live (CAREFUL!)

**Only when ready:**

1. Update Railway env: `ENVIRONMENT=live`
2. Redeploy
3. **Monitor closely**

---

## Part 2: Deploy Dashboard to Vercel (Optional)

### 1. Prepare Dashboard

Update `dashboard/index.html`:

```javascript
// Change this:
const API_URL = 'http://localhost:8000/api';

// To your Railway URL:
const API_URL = 'https://your-railway-app.up.railway.app/api';
```

### 2. Deploy to Vercel

```bash
cd dashboard
npx vercel --prod
```

Or use Vercel web UI:
1. Go to https://vercel.com
2. Import GitHub repo
3. Set root directory to `dashboard/`
4. Deploy

### 3. Open Dashboard

Visit your Vercel URL (e.g., `btc-bot-dashboard.vercel.app`)

You should see:
- Real-time BTC price
- Feed latency
- Active positions
- Stats updating every 500ms

---

## Monitoring After Deployment

### Railway Logs

Watch for:
```json
{"event": "edge_detected", "edge_pct": 3.2, ...}
{"event": "order_executed", "execution_time_ms": 87, ...}
{"event": "position_closed", "pnl": 15.50, ...}
```

### Dashboard

- Feed latency should be <100ms
- Execution time should be <200ms
- Positions update in real-time

### Telegram Alerts (TODO)

Future: Add Telegram bot for alerts on:
- Large edges detected (>5%)
- Positions opened/closed
- Errors

---

## Troubleshooting

### Bot won't start

**Check logs for:**
- `POLYMARKET_PRIVATE_KEY` missing
- Invalid private key format
- Network connectivity

**Fix:**
- Verify env vars in Railway
- Check private key is valid Polygon address

### WebSocket disconnects

**Symptoms:**
```
price_feed_error: Connection closed
```

**Fix:**
- Auto-reconnects after 1 second
- Check Railway network status

### No markets found

**Symptoms:**
```
no_active_markets
```

**Fix:**
- 5-minute markets may not be live yet
- Check Polymarket website manually
- Wait for markets to appear

### Dashboard not updating

**Check:**
- API URL is correct in `index.html`
- Railway bot is running
- CORS is enabled (already in code)

### High execution times

**Symptoms:**
```
slow_cycle: time_ms=250
```

**Fix:**
- Railway free tier may be slow
- Upgrade to Railway Pro ($5/mo)
- Check bot location (closer to Polymarket servers)

---

## Scaling

### Free Tier Limits

- Railway: 500 hours/month (enough for 24/7)
- Vercel: Unlimited static hosting

### Upgrade When

- Execution time consistently >200ms
- Missing opportunities due to speed
- Need 99.9% uptime

### Costs

- Railway Pro: $5/month (faster)
- Vercel Pro: Free for dashboards

---

## Security Checklist

- [ ] Private key in Railway env (NEVER in code)
- [ ] `.env` in `.gitignore`
- [ ] GitHub repo is private (or public without secrets)
- [ ] Start with paper mode
- [ ] Test with small amounts first

---

## Next Steps After Deployment

1. **Monitor for 24 hours** in paper mode
2. **Analyze results:**
   - How many edges detected?
   - What's the win rate?
   - Average PnL per trade?
3. **Optimize if needed:**
   - Adjust `MIN_EDGE_PCT`
   - Tune position sizing
   - Add filters
4. **Go live** with small stakes
5. **Scale gradually** as confidence grows

---

**You're ready to deploy! 🚀**

Remember:
- Start with paper mode
- Test thoroughly
- Monitor closely
- Scale slowly
