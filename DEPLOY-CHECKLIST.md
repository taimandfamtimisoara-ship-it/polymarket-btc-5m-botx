# 🚀 Deployment Checklist — BTC 5m Bot

## ✅ Pre-Deployment

**Location:** `C:\Users\Administrator\Desktop\polymarket-bots\btc-5m-bot\`

**Files ready:**
- [x] Bot code (7 Python modules)
- [x] Dashboard with life meter
- [x] Dockerfile
- [x] railway.json
- [x] requirements.txt

---

## Step 1: GitHub (Optional but Recommended)

**Create repo:**
1. Go to: https://github.com/new
2. Account: `taimandfamtimisoara-ship-it`
3. Name: `polymarket-btc-5m-bot`
4. Private: ✅
5. Create repository

**Push code:**
```bash
cd C:\Users\Administrator\Desktop\polymarket-bots\btc-5m-bot

# If using HTTPS with token
git remote set-url origin https://<TOKEN>@github.com/taimandfamtimisoara-ship-it/polymarket-btc-5m-bot.git
git push -u origin main

# OR skip GitHub and deploy from Railway CLI (see Step 2B)
```

---

## Step 2A: Railway (from GitHub)

**Deploy:**
1. Go to: https://railway.app/new
2. Click "Deploy from GitHub repo"
3. Connect `taimandfamtimisoara-ship-it` account
4. Select `polymarket-btc-5m-bot`
5. Railway auto-detects Dockerfile ✅

---

## Step 2B: Railway (from CLI - No GitHub needed)

```bash
cd C:\Users\Administrator\Desktop\polymarket-bots\btc-5m-bot

# Login
railway login

# Create project
railway init

# Deploy
railway up
```

---

## Step 3: Environment Variables (Railway Dashboard)

**Add these in Railway → Variables:**

| Variable | Value | Notes |
|----------|-------|-------|
| `ENVIRONMENT` | `paper` | Start with paper trading! |
| `POLYMARKET_PRIVATE_KEY` | `your_polygon_wallet_key` | **NEVER commit this!** |
| `POLYMARKET_HOST` | `https://clob.polymarket.com` | Production API |
| `MAX_BET_PCT` | `20` | Max 20% per trade |
| `MAX_CONCURRENT_POSITIONS` | `10` | Max 10 positions |
| `MIN_EDGE_PCT` | `2` | 2% minimum edge |
| `MAX_LATENCY_MS` | `100` | 100ms max latency |

**To get Polygon private key:**
- Use a fresh wallet (not main wallet!)
- Export private key from MetaMask/Rabby
- Fund with small amount for testing (~$50-100 USDC on Polygon)

---

## Step 4: Verify Deployment

**Check Railway logs:**
```
✓ bot_initialized
✓ price_feed_connected source=binance
✓ bot_started mode=paper
```

**If you see these → Bot is alive! 🎉**

---

## Step 5: Update Dashboard (Point to Railway)

**Get Railway URL:**
- Railway dashboard → your project → Settings → Generate Domain
- Example: `btc-bot-abc123.up.railway.app`

**Update dashboard:**

In `dashboard/index.html`, change line ~470:
```javascript
// OLD:
const API_URL = 'http://localhost:8000/api';

// NEW:
const API_URL = 'https://YOUR-RAILWAY-URL.up.railway.app/api';
```

**Redeploy dashboard:**
```bash
cd C:\Users\Administrator\Desktop\polymarket-bots\btc-5m-bot\dashboard
npx vercel --prod
```

---

## Step 6: Test Everything

**Dashboard:** https://dashboard-steel-rho-49.vercel.app

**Should show:**
- ● Online (green status)
- Real BTC price
- Feed latency <100ms
- Bot life meter updating
- Bot messages changing

**Paper Trading Test:**
- Let it run for 1-2 hours
- Check Railway logs for `edge_detected` events
- Verify `paper_trade` logs (no real orders)
- Monitor for errors

---

## Step 7: Go Live (CAREFUL!)

**Only when:**
- [ ] Paper trading works for 24+ hours
- [ ] No critical errors
- [ ] Edges are being detected
- [ ] You understand the risks

**Switch to live:**
1. Railway → Variables → Change `ENVIRONMENT=live`
2. Start with SMALL wallet (~$50-100)
3. Monitor CLOSELY for first hour
4. Check positions in dashboard
5. Verify trades on Polymarket

---

## Troubleshooting

**Bot won't start:**
- Check Railway logs for errors
- Verify `POLYMARKET_PRIVATE_KEY` is valid
- Ensure wallet has USDC on Polygon

**Dashboard shows "Offline":**
- Check Railway URL is correct in dashboard
- Verify bot is running (Railway logs)
- Check CORS (should be enabled in code)

**No markets found:**
- 5-minute markets may not be live yet
- Check Polymarket website manually
- Wait for markets to appear

**High latency:**
- Railway free tier may be slow
- Upgrade to Railway Pro ($5/mo)
- Check bot location/region

---

## Safety Checklist

- [ ] Using separate GitHub account
- [ ] Private repository (not public)
- [ ] Separate wallet (not main funds)
- [ ] Started in paper mode
- [ ] Small test amount (<$100)
- [ ] Monitoring dashboard
- [ ] Railway logs visible

---

## Quick Reference

**Dashboard:** https://dashboard-steel-rho-49.vercel.app  
**Railway:** https://railway.app/dashboard  
**Polymarket:** https://polymarket.com  

**Local folder:** `C:\Users\Administrator\Desktop\polymarket-bots\btc-5m-bot\`

---

**You're ready! 🚀**

Start with paper mode → Monitor → Test → Go live small → Scale gradually.

Good luck! May your bot survive the API costs! 🤖💪
