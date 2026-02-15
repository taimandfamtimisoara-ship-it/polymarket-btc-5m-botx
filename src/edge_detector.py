"""Edge detection: BTC price vs Polymarket odds - SPEED OPTIMIZED."""
import structlog
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass
from indicators import momentum_indicators, IndicatorSignals

logger = structlog.get_logger()


@dataclass
class Edge:
    """Trading edge/opportunity."""
    market_id: str
    market_question: str
    direction: str  # "YES" or "NO"
    edge_pct: float  # How much edge we have
    current_price: float  # BTC price
    market_yes_price: float  # Polymarket YES price
    market_no_price: float  # Polymarket NO price
    confidence: float  # 0-1, how confident we are
    detected_at: datetime
    indicators: Optional[IndicatorSignals] = None  # Momentum indicators
    
    def __str__(self):
        base = (f"Edge: {self.direction} @ {self.edge_pct:.2f}% "
                f"(BTC: ${self.current_price:,.0f}, "
                f"Market: Y={self.market_yes_price:.3f} N={self.market_no_price:.3f})")
        if self.indicators:
            base += f" | {self.indicators}"
        return base


class EdgeDetector:
    """
    Detects profitable opportunities by comparing:
    - Real BTC price (from price feed)
    - Polymarket 5-minute market odds
    
    Strategy:
    - If BTC moved UP but market odds haven't caught up → BET YES
    - If BTC moved DOWN but market odds haven't caught up → BET NO
    - Minimum edge threshold from config (default 2%)
    """
    
    def __init__(self, min_edge_pct: float = 2.0):
        self.min_edge_pct = min_edge_pct
        self.last_check = None
        
    def calculate_edge(
        self,
        current_price: float,
        baseline_price: float,  # Price at market creation
        market_yes_price: float,
        market_no_price: float,
        market_question: str,
        market_id: str,
        price_history: Optional[List[float]] = None
    ) -> Optional[Edge]:
        """
        Calculate edge for a 5-minute BTC market.
        
        Logic:
        1. Calculate real BTC movement: (current - baseline) / baseline
        2. Calculate implied movement from market: yes_price - 0.5
        3. Edge = real_movement - implied_movement
        4. If edge > threshold → opportunity
        
        Example:
        - BTC moved +0.5% (real)
        - Market shows YES at 0.45 (implying -0.05 or +5%)
        - Edge = we think it should be higher → BET YES
        """
        
        # 1. Real BTC movement
        real_movement_pct = ((current_price - baseline_price) / baseline_price) * 100
        
        # 2. Market implied movement
        # YES price above 0.5 = market expects UP
        # YES price below 0.5 = market expects DOWN
        market_implied_up_pct = (market_yes_price - 0.5) * 100
        
        # 3. Calculate edge
        edge_pct = real_movement_pct - market_implied_up_pct
        
        # 4. Calculate momentum indicators (if price history available)
        indicators = None
        if price_history and len(price_history) >= 15:  # Minimum for RSI
            indicators = momentum_indicators.get_signals(price_history)
        
        # 5. Determine direction
        if edge_pct > self.min_edge_pct:
            # Real price moved UP more than market expects → BET YES
            direction = "YES"
            confidence = min(abs(edge_pct) / 10, 1.0)  # Higher edge = higher confidence
            
        elif edge_pct < -self.min_edge_pct:
            # Real price moved DOWN more than market expects → BET NO
            direction = "NO"
            edge_pct = abs(edge_pct)
            confidence = min(edge_pct / 10, 1.0)
            
        else:
            # No edge
            return None
        
        # 6. Adjust confidence based on indicators
        if indicators:
            confidence = momentum_indicators.boost_confidence(confidence, direction, indicators)
        
        # Log detection with indicators
        log_data = {
            "direction": direction,
            "edge_pct": round(edge_pct, 2),
            "confidence": round(confidence, 2),
            "real_move": round(real_movement_pct, 3),
            "market_implied": round(market_implied_up_pct, 3),
            "btc_price": round(current_price, 2),
            "yes_price": round(market_yes_price, 3)
        }
        
        if indicators:
            log_data.update({
                "rsi": round(indicators.rsi, 1) if indicators.rsi else None,
                "rsi_signal": indicators.rsi_signal,
                "macd_trend": indicators.macd_trend,
                "indicator_alignment": round(indicators.alignment_score, 2)
            })
        
        logger.info("edge_detected", **log_data)
        
        return Edge(
            market_id=market_id,
            market_question=market_question,
            direction=direction,
            edge_pct=edge_pct,
            current_price=current_price,
            market_yes_price=market_yes_price,
            market_no_price=market_no_price,
            confidence=confidence,
            detected_at=datetime.now(),
            indicators=indicators
        )
    
    def scan_markets(
        self,
        current_price: float,
        markets: List[Dict],
        price_history: Optional[List[float]] = None
    ) -> List[Edge]:
        """
        Scan all active 5-minute markets for edges.
        
        Args:
            current_price: Current BTC price from feed
            markets: List of Polymarket 5m markets with baseline prices
            
        Returns:
            List of detected edges
        """
        edges = []
        
        for market in markets:
            edge = self.calculate_edge(
                current_price=current_price,
                baseline_price=market['baseline_price'],
                market_yes_price=market['yes_price'],
                market_no_price=market['no_price'],
                market_question=market['question'],
                market_id=market['id'],
                price_history=price_history
            )
            
            if edge:
                edges.append(edge)
        
        self.last_check = datetime.now()
        
        logger.info(
            "market_scan_complete",
            total_markets=len(markets),
            edges_found=len(edges)
        )
        
        return edges
    
    def prioritize_edges(self, edges: List[Edge]) -> List[Edge]:
        """
        Sort edges by attractiveness.
        
        Priority:
        1. Higher edge %
        2. Higher confidence
        """
        return sorted(
            edges,
            key=lambda e: (e.edge_pct * e.confidence),
            reverse=True
        )


# Singleton
edge_detector = EdgeDetector()
