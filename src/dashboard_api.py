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
from pnl_calculator import pnl_calculator
from health_monitor import health_monitor
from survival_brain import SurvivalBrain

# Global survival brain instance (set by main bot)
survival_brain: Optional[SurvivalBrain] = None


def set_survival_brain(brain: SurvivalBrain):
    """Set the global survival brain instance (called by main bot)."""
    global survival_brain
    survival_brain = brain
    logger.info("dashboard_survival_brain_attached")

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


@app.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint.
    
    Returns:
    - Overall status: healthy/degraded/unhealthy
    - Component-level health (price feed, main loop, API, memory)
    - Health check duration
    - Uptime
    
    Fast: <100ms target
    """
    if not health_monitor:
        return {
            "status": "degraded",
            "message": "Health monitor not initialized",
            "timestamp": datetime.now().isoformat()
        }
    
    # Run comprehensive health check
    health_report = await health_monitor.check_health()
    
    return health_report


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
    - Real-time PnL (unrealized + realized)
    - Health status
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
    
    # Calculate real-time PnL
    unrealized_pnl = 0.0
    realized_pnl = 0.0
    total_pnl = 0.0
    
    if pnl_calculator and execution_engine:
        try:
            positions = execution_engine.get_active_positions()
            pnl_data = await pnl_calculator.calculate_portfolio_pnl(positions)
            unrealized_pnl = pnl_data['unrealized_pnl']
            realized_pnl = pnl_data['realized_pnl']
            total_pnl = pnl_data['total_pnl']
        except Exception as e:
            logger.error("pnl_calculation_failed_in_stats", error=str(e))
    
    # Get health status
    health_status = "unknown"
    health_components = []
    
    if health_monitor:
        try:
            health_report = await health_monitor.check_health()
            health_status = health_report['status']
            health_components = health_report['components']
        except Exception as e:
            logger.error("health_check_failed_in_stats", error=str(e))
    
    return {
        'current_price': current_price,
        'feed_latency_ms': round(feed_latency, 2) if feed_latency else None,
        'feed_connected': price_feed.is_connected,
        'active_positions': active_positions,
        'edges_detected': bot_stats['edges_detected'],
        'orders_executed': bot_stats['orders_executed'],
        'avg_execution_time_ms': round(avg_execution_time, 2) if avg_execution_time else None,
        'uptime_seconds': round(uptime_seconds, 1) if uptime_seconds else None,
        'unrealized_pnl': unrealized_pnl,
        'realized_pnl': realized_pnl,
        'total_pnl': total_pnl,
        'health_status': health_status,
        'health_components': health_components,
        'timestamp': datetime.now().isoformat()
    }


@app.get("/api/positions")
async def get_positions():
    """
    Get active positions with real-time PnL.
    
    Returns list of open positions with:
    - Market ID
    - Direction (YES/NO)
    - Entry price
    - Current price (from live market data)
    - Unrealized PnL (calculated in real-time)
    - Time held
    """
    if not execution_engine:
        return {"positions": []}
    
    positions = execution_engine.get_active_positions()
    current_btc_price = price_feed.get_current_price()
    
    positions_list = []
    total_unrealized_pnl = 0.0
    
    for market_id, pos in positions.items():
        # Get market data
        market = None
        if market_fetcher:
            market = market_fetcher.get_market_by_id(market_id)
        
        # Calculate time held
        time_held_seconds = (datetime.now() - pos['opened_at']).total_seconds()
        
        # Calculate real PnL using pnl_calculator
        pnl = 0.0
        current_market_price = None
        
        if pnl_calculator:
            try:
                pnl, current_market_price = await pnl_calculator.calculate_position_pnl(pos, market)
                total_unrealized_pnl += pnl
            except Exception as e:
                logger.error("position_pnl_calc_failed", market_id=market_id, error=str(e))
        
        positions_list.append({
            'market_id': market_id,
            'question': market['question'] if market else "Unknown",
            'direction': pos['direction'],
            'size': pos['size'],
            'entry_price': pos['entry_price'],
            'current_price': current_market_price,
            'entry_btc_price': pos['btc_price'],
            'current_btc_price': current_btc_price,
            'edge_pct': pos['edge_pct'],
            'time_held_seconds': round(time_held_seconds, 1),
            'pnl': round(pnl, 2),
            'pnl_percent': round((pnl / pos['size']) * 100, 2) if pos['size'] > 0 else 0.0,
            'opened_at': pos['opened_at'].isoformat()
        })
    
    return {
        'positions': positions_list,
        'count': len(positions_list),
        'total_unrealized_pnl': round(total_unrealized_pnl, 2),
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


@app.get("/api/survival")
async def get_survival_status():
    """
    Get survival brain status and metrics.
    
    Returns:
    - Current survival state (THRIVING/HEALTHY/WOUNDED/CRITICAL/DEAD)
    - Capital percentage
    - Runway days (if losing money)
    - Daily/weekly targets and PnL
    - Position sizing modifiers
    - Pattern learning stats
    
    Fast: <50ms target
    """
    if not survival_brain:
        return {
            "error": "Survival brain not initialized",
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        # Get comprehensive survival metrics
        metrics = survival_brain.get_survival_status()
        
        # Convert to dict for JSON response
        status = metrics.to_dict()
        status['timestamp'] = datetime.now().isoformat()
        
        # Add pattern details (top winners and losers)
        patterns_summary = []
        
        # Get all patterns with enough sample size
        valid_patterns = [
            (key, pattern) for key, pattern in survival_brain.patterns.items()
            if pattern.sample_size >= survival_brain.min_pattern_sample_size
        ]
        
        # Sort by win rate (best and worst)
        valid_patterns.sort(key=lambda x: x[1].win_rate, reverse=True)
        
        # Top 5 best patterns
        for key, pattern in valid_patterns[:5]:
            hour, market_type, edge_bucket = key.split('|')
            patterns_summary.append({
                'type': 'winner',
                'hour': int(hour),
                'market_type': market_type,
                'edge_bucket': edge_bucket,
                'win_rate': round(pattern.win_rate, 1),
                'sample_size': pattern.sample_size,
                'avg_pnl': round(pattern.avg_pnl, 2)
            })
        
        # Top 5 worst patterns
        for key, pattern in valid_patterns[-5:]:
            hour, market_type, edge_bucket = key.split('|')
            patterns_summary.append({
                'type': 'loser',
                'hour': int(hour),
                'market_type': market_type,
                'edge_bucket': edge_bucket,
                'win_rate': round(pattern.win_rate, 1),
                'sample_size': pattern.sample_size,
                'avg_pnl': round(pattern.avg_pnl, 2)
            })
        
        status['patterns_summary'] = patterns_summary
        
        return status
    
    except Exception as e:
        logger.error("survival_status_failed", error=str(e))
        return {
            "error": f"Failed to get survival status: {str(e)}",
            "timestamp": datetime.now().isoformat()
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
