"""Order placement, cancellation, and reconciliation against IBKR."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import pandas as pd
from ib_insync import IB, LimitOrder, MarketOrder, Stock, StopOrder, Trade

from .logger import TradeLogger
from .portfolio import Portfolio
from .risk_guard import RiskGuard

logger = logging.getLogger(__name__)

_VALID_TYPES = {"MARKET", "LIMIT", "STOP"}


class OrderRejectedError(Exception):
    """Raised when an order is blocked by the risk guard."""


class OrderManager:
    """Place and manage orders, gated by :class:`RiskGuard` and audited via :class:`TradeLogger`."""

    def __init__(
        self,
        ib: IB,
        risk_guard: RiskGuard,
        portfolio: Portfolio,
        trade_logger: TradeLogger,
    ) -> None:
        self.ib = ib
        self.risk_guard = risk_guard
        self.portfolio = portfolio
        self.trade_logger = trade_logger

    def _build_order(self, side: str, quantity: float, order_type: str, limit_price: Optional[float]):
        order_type = order_type.upper()
        if order_type not in _VALID_TYPES:
            raise ValueError(f"Unsupported order_type {order_type!r}; expected one of {_VALID_TYPES}")
        if order_type == "MARKET":
            return MarketOrder(side, quantity)
        if order_type == "LIMIT":
            if limit_price is None:
                raise ValueError("LIMIT orders require a limit_price")
            return LimitOrder(side, quantity, limit_price)
        if order_type == "STOP":
            if limit_price is None:
                raise ValueError("STOP orders require a stop price (limit_price arg)")
            return StopOrder(side, quantity, limit_price)
        raise ValueError(order_type)  # unreachable

    def _resolve_contract(self, symbol: str) -> Stock:
        contract = Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"Could not qualify contract for {symbol}")
        return qualified[0]

    def _estimate_price(self, symbol: str, limit_price: Optional[float]) -> float:
        if limit_price is not None:
            return limit_price
        contract = self._resolve_contract(symbol)
        ticker = self.ib.reqMktData(contract, snapshot=True)
        self.ib.sleep(1)
        price = ticker.marketPrice() or ticker.last or ticker.close or 0.0
        self.ib.cancelMktData(contract)
        return float(price)

    def _place(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        limit_price: Optional[float],
    ) -> Trade:
        estimated = self._estimate_price(symbol, limit_price)
        allowed, reason = self.risk_guard.check(symbol, quantity, side, self.portfolio, estimated)
        if not allowed:
            self.trade_logger.log_event("RISK_REJECT", f"{side} {quantity} {symbol}: {reason}")
            raise OrderRejectedError(reason)

        contract = self._resolve_contract(symbol)
        order = self._build_order(side, quantity, order_type, limit_price)
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(1)  # allow status to populate

        fill_price = trade.orderStatus.avgFillPrice or estimated
        self.trade_logger.log_trade(
            timestamp=datetime.now(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=fill_price,
            order_type=order_type.upper(),
            status=trade.orderStatus.status,
        )
        return trade

    def buy(
        self,
        symbol: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Trade:
        """Submit a BUY order, gated by the risk guard."""
        return self._place(symbol, "BUY", quantity, order_type, limit_price)

    def sell(
        self,
        symbol: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Trade:
        """Submit a SELL order, gated by the risk guard."""
        return self._place(symbol, "SELL", quantity, order_type, limit_price)

    def close_position(self, symbol: str) -> Optional[Trade]:
        """Flatten the entire current position in ``symbol`` (if any)."""
        positions = self.portfolio.get_positions()
        if positions.empty:
            logger.info("No open positions to close.")
            return None
        row = positions[positions["symbol"] == symbol]
        if row.empty:
            logger.info("No position in %s to close.", symbol)
            return None

        qty = float(row.iloc[0]["quantity"])
        if qty == 0:
            return None
        side = "SELL" if qty > 0 else "BUY"
        return self._place(symbol, side, abs(qty), "MARKET", None)

    def get_open_orders(self) -> pd.DataFrame:
        """Return all currently open orders as a DataFrame."""
        rows = []
        for trade in self.ib.openTrades():
            rows.append(
                {
                    "order_id": trade.order.orderId,
                    "symbol": trade.contract.symbol,
                    "side": trade.order.action,
                    "quantity": trade.order.totalQuantity,
                    "type": trade.order.orderType,
                    "status": trade.orderStatus.status,
                }
            )
        return pd.DataFrame(
            rows,
            columns=["order_id", "symbol", "side", "quantity", "type", "status"],
        )

    def cancel_order(self, order_id: int) -> bool:
        """Cancel a single open order by id. Returns True if a match was cancelled."""
        for trade in self.ib.openTrades():
            if trade.order.orderId == order_id:
                self.ib.cancelOrder(trade.order)
                self.trade_logger.log_event("ORDER_CANCEL", f"orderId={order_id}")
                return True
        return False

    def cancel_all(self) -> List[int]:
        """Cancel every open order. Returns the list of cancelled order ids."""
        cancelled: List[int] = []
        for trade in self.ib.openTrades():
            self.ib.cancelOrder(trade.order)
            cancelled.append(trade.order.orderId)
        if cancelled:
            self.trade_logger.log_event("ORDER_CANCEL_ALL", f"ids={cancelled}")
        return cancelled
