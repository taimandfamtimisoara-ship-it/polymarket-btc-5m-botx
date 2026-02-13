"""Real-time dashboard API - serves data for frontend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Optional, Dict, List
import structlog

from price_feed import price_feed
from edge_detector import edge_detector
from execution_engine import execution_engine
from market_fetcher import market_fetcher

logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(title="BTC 5m Bot Dashboard API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global bot stats (updated by main bot)
bot_stats = {
    'started_at': None,
    'edges_detected': 0,
    'orders_executed': 0,
    'total_pnl': 0.0
}


@app.get("/")
async def root():
    """API health check."""
    return {
        "status": "online",
        "bot": "BTC 5-Minute Trading Bot",
        "version": "1.0.0"
    }


@app.get("/api/stats")
async def get_stats():
    """
    Get overall bot statistics.
    
    Returns:
    - Current BTC price
    - Feed latency
    - Active positions count
    - Edges detected
    - Orders executed
    - Average execution time
    - Uptime
    """
    current_price = price_feed.get_current_price()
    feed_latency = price_feed.get_latency_ms()
    
    active_positions = 0
    avg_execution_time = None
    
    if execution_engine:
        active_positions = execution_engine.get_position_count()
        avg_execution_time = execution_engine.get_avg_execution_time_ms()
    
    # Calculate uptime
    uptime_seconds = None
    if bot_stats['started_at']:
        uptime_seconds = (datetime.now() - bot_stats['started_at']).total_seconds()
    
    return {
        'current_price': current_price,
        'feed_latency_ms': round(feed_latency, 2) if feed_latency else None,
        'feed_connected': price_feed.is_connected,
        'active_positions': active_positions,
        'edges_detected': bot_stats['edges_detected'],
        'orders_executed': bot_stats['orders_executed'],
        'avg_execution_time_ms': round(avg_execution_time, 2) if avg_execution_time else None,
        'uptime_seconds': round(uptime_seconds, 1) if uptime_seconds else None,
        'total_pnl': bot_stats.get('total_pnl', 0.0),
        'timestamp': datetime.now().isoformat()
    }


@app.get("/api/positions")
async def get_positions():
    """
    Get active positions.
    
    Returns list of open positions with:
    - Market ID
    - Direction (YES/NO)
    - Entry price
    - Current price
    - PnL
    - Time held
    """
    if not execution_engine:
        return {"positions": []}
    
    positions = execution_engine.get_active_positions()
    current_price = price_feed.get_current_price()
    
    positions_list = []
    
    for market_id, pos in positions.items():
        # Get market data
        market = None
        if market_fetcher:
            market = market_fetcher.get_market_by_id(market_id)
        
        # Calculate time held
        time_held_seconds = (datetime.now() - pos['opened_at']).total_seconds()
        
        # Calculate current value (placeholder - need real market data)
        # For now, just show entry
        current_value = pos['size']  # TODO: Get real current value from market
        pnl = 0  # TODO: Calculate real PnL
        
        positions_list.append({
            'market_id': market_id,
            'question': market['question'] if market else "Unknown",
            'direction': pos['direction'],
            'size': pos['size'],
            'entry_price': pos['entry_price'],
            'entry_btc_price': pos['btc_price'],
            'current_btc_price': current_price,
            'edge_pct': pos['edge_pct'],
            'time_held_seconds': round(time_held_seconds, 1),
            'pnl': round(pnl, 2),
            'opened_at': pos['opened_at'].isoformat()
        })
    
    return {
        'positions': positions_list,
        'count': len(positions_list),
        'timestamp': datetime.now().isoformat()
    }


@app.get("/api/markets")
async def get_markets():
    """
    Get active 5-minute markets.
    
    Returns list of markets being monitored.
    """
    if not market_fetcher:
        return {"markets": []}
    
    markets = await market_fetcher.get_active_markets()
    
    return {
        'markets': markets,
        'count': len(markets),
        'timestamp': datetime.now().isoformat()
    }


@app.get("/api/price-history")
async def get_price_history():
    """
    Get recent BTC price history.
    
    TODO: Implement price history tracking.
    For now, just return current price.
    """
    current_price = price_feed.get_current_price()
    
    return {
        'current': current_price,
        'history': [],  # TODO: Track price history
        'timestamp': datetime.now().isoformat()
    }


@app.post("/api/update-stats")
async def update_stats(stats: Dict):
    """
    Update bot statistics (called by main bot).
    
    Internal endpoint for bot to push stats to dashboard.
    """
    global bot_stats
    bot_stats.update(stats)
    
    return {"status": "updated"}


# Run with: uvicorn dashboard_api:app --reload --port 8000
