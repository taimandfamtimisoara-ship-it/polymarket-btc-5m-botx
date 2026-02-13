"""Polymarket client - optimized for speed."""
import asyncio
from typing import List, Dict, Optional
import structlog

from .config import settings

logger = structlog.get_logger()


class PolymarketClient:
    """Fast Polymarket integration."""
    
    def __init__(self):
        from py_clob_client.client import ClobClient
        
        self.client = ClobClient(
            host=settings.polymarket_api_url,
            key=settings.polygon_wallet_private_key,
            chain_id=settings.polygon_chain_id,
            funder=settings.polymarket_funder_address
        )
    
    def get_btc_5m_markets(self) -> List[Dict]:
        """
        Get all active 5-minute BTC markets.
        
        Returns markets with:
        - market_id
        - question
        - yes_price
        - no_price
        - end_time
        """
        try:
            # Get all markets
            all_markets = self.client.get_markets()
            
            # Filter for BTC 5-minute markets
            btc_5m_markets = []
            
            for market in all_markets:
                question = market.get('question', '').lower()
                
                # Check if it's a BTC market
                if 'btc' not in question and 'bitcoin' not in question:
                    continue
                
                # Check if it's a 5-minute market
                # Look for time indicators in question or market metadata
                if '5 min' in question or '5-min' in question or '5min' in question:
                    btc_5m_markets.append({
                        'market_id': market['id'],
                        'question': market['question'],
                        'yes_price': market.get('yes_price', 0),
                        'no_price': market.get('no_price', 0),
                        'end_time': market.get('end_date'),
                        'volume': market.get('volume', 0)
                    })
            
            return btc_5m_markets
        
        except Exception as e:
            logger.error("get_markets_failed", error=str(e), exc_info=True)
            return []
    
    def place_order(
        self,
        market_id: str,
        side: str,
        amount: float,
        price: float
    ) -> Optional[Dict]:
        """
        Place order - FAST execution.
        
        Args:
            market_id: Market ID
            side: 'YES' or 'NO'
            amount: Amount in USD
            price: Limit price (0-1)
        
        Returns:
            Order data or None
        """
        try:
            # Use market order for SPEED
            order = self.client.create_market_order(
                market_id=market_id,
                side=side,
                amount=amount
            )
            
            logger.info(
                "order_placed",
                market_id=market_id,
                side=side,
                amount=amount,
                order_id=order.get('id')
            )
            
            return order
        
        except Exception as e:
            logger.error(
                "order_failed",
                error=str(e),
                market_id=market_id,
                exc_info=True
            )
            return None
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """Get specific market data."""
        try:
            market = self.client.get_market(market_id)
            if market:
                return {
                    'market_id': market['id'],
                    'question': market['question'],
                    'yes_price': market.get('yes_price', 0),
                    'no_price': market.get('no_price', 0),
                    'resolved': market.get('resolved', False)
                }
        except Exception as e:
            logger.error("get_market_failed", error=str(e), market_id=market_id)
        return None
    
    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        try:
            return self.client.get_positions()
        except Exception as e:
            logger.error("get_positions_failed", error=str(e))
            return []
