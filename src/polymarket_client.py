"""Polymarket client - optimized for speed."""
import structlog
from typing import List, Dict, Optional
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from .config import settings

logger = structlog.get_logger()


class PolymarketClient:
    """Fast Polymarket integration using py-clob-client."""
    
    def __init__(self):
        """Initialize CLOB client with settings."""
        try:
            # Initialize client
            self.client = ClobClient(
                host=settings.polymarket_api_url,
                key=settings.polygon_wallet_private_key,
                chain_id=settings.polygon_chain_id,
                signature_type=1,  # Email/Magic wallet signatures
                funder=settings.polymarket_funder_address
            )
            
            # Set API credentials
            creds = self.client.create_or_derive_api_creds()
            if creds:
                self.client.set_api_creds(creds)
                logger.info("polymarket_client_initialized", address=self.client.get_address())
            else:
                logger.error("failed_to_create_api_creds")
                
        except Exception as e:
            logger.error("polymarket_client_init_failed", error=str(e), exc_info=True)
            raise
    
    def get_btc_5m_markets(self) -> List[Dict]:
        """
        Get all active 5-minute BTC markets.
        
        Note: This is a wrapper method. Market filtering should be done
        by MarketFetcher which has better filtering logic.
        
        Returns markets with:
        - market_id
        - question
        - tokens (YES/NO token IDs)
        - end_time
        """
        try:
            # Get simplified markets from CLOB
            result = self.client.get_simplified_markets()
            
            # Parse response
            markets = []
            if isinstance(result, dict) and 'data' in result:
                markets = result['data']
            elif isinstance(result, list):
                markets = result
            
            # Filter for BTC 5-minute markets
            btc_5m_markets = []
            for market in markets:
                question = market.get('question', '').lower()
                
                # Check if it's a BTC market
                if 'btc' not in question and 'bitcoin' not in question:
                    continue
                
                # Check if it's a 5-minute market
                if any(term in question for term in ['5 min', '5-min', '5min', '5 minute']):
                    btc_5m_markets.append({
                        'market_id': market.get('condition_id') or market.get('id'),
                        'question': market.get('question'),
                        'tokens': market.get('tokens', []),
                        'end_time': market.get('end_date_iso'),
                        'volume': market.get('volume', 0)
                    })
            
            return btc_5m_markets
        
        except Exception as e:
            logger.error("get_markets_failed", error=str(e), exc_info=True)
            return []
    
    def get_market_price(self, token_id: str, side: str = "BUY") -> float:
        """
        Get current market price for a token.
        
        Args:
            token_id: Token ID to get price for
            side: "BUY" or "SELL"
        
        Returns:
            Price as float (0.0 - 1.0)
        """
        try:
            result = self.client.get_price(token_id, side)
            
            if isinstance(result, dict):
                return float(result.get('price', 0.5))
            
            return 0.5
            
        except Exception as e:
            logger.warning("get_price_failed", token_id=token_id, error=str(e))
            return 0.5
    
    def get_midpoint(self, token_id: str) -> float:
        """
        Get midpoint price for a token.
        
        Args:
            token_id: Token ID
        
        Returns:
            Midpoint price (0.0 - 1.0)
        """
        try:
            result = self.client.get_midpoint(token_id)
            
            if isinstance(result, dict):
                return float(result.get('mid', 0.5))
            
            return 0.5
            
        except Exception as e:
            logger.warning("get_midpoint_failed", token_id=token_id, error=str(e))
            return 0.5
    
    def place_order(
        self,
        token_id: str,
        side: str,
        amount: float,
        price: Optional[float] = None
    ) -> Optional[Dict]:
        """
        Place order - FAST execution using market orders.
        
        Args:
            token_id: Token ID to trade
            side: 'BUY' or 'SELL'
            amount: Amount in USD
            price: Optional limit price (0-1). If None, uses market order.
        
        Returns:
            Order data or None
        """
        try:
            # Convert side string to constant
            side_const = BUY if side.upper() == 'BUY' else SELL
            
            if price is None:
                # Market order for SPEED
                market_order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount,
                    side=side_const,
                    order_type=OrderType.FOK  # Fill-or-Kill for speed
                )
                
                signed_order = self.client.create_market_order(market_order_args)
                result = self.client.post_order(signed_order, OrderType.FOK)
                
                logger.info(
                    "market_order_placed",
                    token_id=token_id,
                    side=side,
                    amount=amount,
                    order_id=result.get('orderID') if isinstance(result, dict) else None
                )
                
                return result
            else:
                # Limit order
                order_args = OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=amount,
                    side=side_const
                )
                
                signed_order = self.client.create_order(order_args)
                result = self.client.post_order(signed_order, OrderType.GTC)
                
                logger.info(
                    "limit_order_placed",
                    token_id=token_id,
                    side=side,
                    amount=amount,
                    price=price,
                    order_id=result.get('orderID') if isinstance(result, dict) else None
                )
                
                return result
        
        except Exception as e:
            logger.error(
                "order_failed",
                error=str(e),
                token_id=token_id,
                side=side,
                amount=amount,
                exc_info=True
            )
            return None
    
    def get_market_by_id(self, condition_id: str) -> Optional[Dict]:
        """
        Get specific market data by condition ID.
        
        Args:
            condition_id: Market condition ID
        
        Returns:
            Market data or None
        """
        try:
            market = self.client.get_market(condition_id)
            
            if market:
                return {
                    'market_id': market.get('condition_id') or market.get('id'),
                    'question': market.get('question'),
                    'tokens': market.get('tokens', []),
                    'resolved': market.get('closed', False),
                    'volume': market.get('volume', 0)
                }
                
        except Exception as e:
            logger.error("get_market_failed", error=str(e), condition_id=condition_id)
        
        return None
    
    def get_positions(self) -> List[Dict]:
        """
        Get all open positions.
        
        Note: This requires querying open orders as py-clob-client
        doesn't have a direct get_positions method.
        
        Returns:
            List of position data
        """
        try:
            from py_clob_client.clob_types import OpenOrderParams
            
            # Get open orders
            orders = self.client.get_orders(OpenOrderParams())
            
            # Group by market/token
            positions = {}
            for order in orders:
                token_id = order.get('asset_id')
                if token_id not in positions:
                    positions[token_id] = {
                        'token_id': token_id,
                        'orders': [],
                        'total_size': 0
                    }
                
                positions[token_id]['orders'].append(order)
                positions[token_id]['total_size'] += float(order.get('original_size', 0))
            
            return list(positions.values())
            
        except Exception as e:
            logger.error("get_positions_failed", error=str(e), exc_info=True)
            return []
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a specific order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.client.cancel(order_id)
            logger.info("order_cancelled", order_id=order_id)
            return True
            
        except Exception as e:
            logger.error("cancel_order_failed", order_id=order_id, error=str(e))
            return False
    
    def cancel_all_orders(self) -> bool:
        """
        Cancel all open orders.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.client.cancel_all()
            logger.info("all_orders_cancelled")
            return True
            
        except Exception as e:
            logger.error("cancel_all_failed", error=str(e))
            return False
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get orderbook for a token.
        
        Args:
            token_id: Token ID
        
        Returns:
            Orderbook data with bids and asks
        """
        try:
            book = self.client.get_order_book(token_id)
            
            return {
                'token_id': token_id,
                'bids': book.bids if hasattr(book, 'bids') else [],
                'asks': book.asks if hasattr(book, 'asks') else [],
                'market': book.market if hasattr(book, 'market') else token_id
            }
            
        except Exception as e:
            logger.error("get_orderbook_failed", token_id=token_id, error=str(e))
            return None
