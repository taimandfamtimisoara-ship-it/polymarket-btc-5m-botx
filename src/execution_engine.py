"""Fast order execution on Polymarket - SPEED OPTIMIZED."""
import asyncio
import structlog
from typing import Optional, Dict
from datetime import datetime
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from decimal import Decimal

from edge_detector import Edge
from config import config

logger = structlog.get_logger()


class ExecutionEngine:
    """
    Ultra-fast order execution.
    
    Goal: <100ms from edge detection to order placement.
    """
    
    def __init__(self, clob_client: ClobClient):
        self.client = clob_client
        self.active_positions = {}  # market_id -> position info
        self.execution_times = []  # Track execution latency
        
    async def execute_edge(self, edge: Edge) -> Optional[Dict]:
        """
        Execute a detected edge with SPEED.
        
        Steps:
        1. Calculate position size
        2. Create order
        3. Submit order
        4. Track position
        
        Target: <100ms total
        """
        start_time = datetime.now()
        
        try:
            # 1. Check if we're at max concurrent positions
            if len(self.active_positions) >= config.MAX_CONCURRENT_POSITIONS:
                logger.warning(
                    "max_positions_reached",
                    current=len(self.active_positions),
                    max=config.MAX_CONCURRENT_POSITIONS
                )
                return None
            
            # 2. Calculate position size
            position_size = self._calculate_position_size(edge)
            
            if position_size <= 0:
                logger.warning("position_size_too_small", edge=str(edge))
                return None
            
            # 3. Create order
            order = self._create_order(edge, position_size)
            
            # 4. Submit order (FAST!)
            result = await self.client.create_order(order)
            
            # 5. Track execution time
            execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000
            self.execution_times.append(execution_time_ms)
            
            # Keep last 100 executions for stats
            if len(self.execution_times) > 100:
                self.execution_times.pop(0)
            
            # 6. Track position
            position_info = {
                'market_id': edge.market_id,
                'direction': edge.direction,
                'size': position_size,
                'entry_price': edge.market_yes_price if edge.direction == "YES" else edge.market_no_price,
                'btc_price': edge.current_price,
                'edge_pct': edge.edge_pct,
                'opened_at': datetime.now(),
                'order_id': result.get('orderID')
            }
            
            self.active_positions[edge.market_id] = position_info
            
            logger.info(
                "order_executed",
                market_id=edge.market_id,
                direction=edge.direction,
                size=position_size,
                edge_pct=round(edge.edge_pct, 2),
                execution_time_ms=round(execution_time_ms, 2),
                order_id=result.get('orderID')
            )
            
            return position_info
            
        except Exception as e:
            logger.error(
                "execution_failed",
                edge=str(edge),
                error=str(e)
            )
            return None
    
    def _calculate_position_size(self, edge: Edge) -> float:
        """
        Calculate position size based on:
        - Edge size (higher edge = larger bet)
        - Confidence
        - Risk limits
        
        Kelly Criterion simplified:
        size = (edge% / 100) * confidence * max_bet%
        """
        # Base size from edge
        edge_factor = min(edge.edge_pct / 10, 1.0)  # Cap at 10% edge = max size
        
        # Apply confidence
        confidence_factor = edge.confidence
        
        # Calculate size
        size_pct = edge_factor * confidence_factor * config.MAX_BET_PCT
        
        # Convert to dollar amount
        # Assuming we have a balance to work with
        # For now, use a placeholder - will integrate with account balance
        hypothetical_balance = 1000  # TODO: Get from account
        size_usd = hypothetical_balance * (size_pct / 100)
        
        # Enforce minimum
        if size_usd < 10:  # Minimum $10 bet
            return 0
        
        return round(size_usd, 2)
    
    def _create_order(self, edge: Edge, size_usd: float) -> OrderArgs:
        """Create Polymarket order from edge."""
        
        # Determine which token to buy (YES or NO)
        token_id = edge.market_id  # TODO: Map to actual token ID
        
        # Price we're willing to pay
        # For YES: use current YES price + small buffer for execution
        # For NO: use current NO price + small buffer
        if edge.direction == "YES":
            price = min(edge.market_yes_price + 0.01, 0.99)  # Small buffer, cap at 0.99
        else:
            price = min(edge.market_no_price + 0.01, 0.99)
        
        # Create order
        order = OrderArgs(
            token_id=token_id,
            price=Decimal(str(price)),
            size=Decimal(str(size_usd)),
            side="BUY",
            orderType=OrderType.GTC  # Good Till Cancelled
        )
        
        return order
    
    def get_position_count(self) -> int:
        """Get current number of active positions."""
        return len(self.active_positions)
    
    def get_avg_execution_time_ms(self) -> Optional[float]:
        """Get average execution time in milliseconds."""
        if not self.execution_times:
            return None
        return sum(self.execution_times) / len(self.execution_times)
    
    def close_position(self, market_id: str):
        """Close/remove a position (after market resolves)."""
        if market_id in self.active_positions:
            del self.active_positions[market_id]
            logger.info("position_closed", market_id=market_id)
    
    def get_active_positions(self) -> Dict:
        """Get all active positions."""
        return self.active_positions


# Note: Initialized in main.py with client
execution_engine: Optional[ExecutionEngine] = None


def init_execution_engine(clob_client: ClobClient):
    """Initialize execution engine."""
    global execution_engine
    execution_engine = ExecutionEngine(clob_client)
    return execution_engine
