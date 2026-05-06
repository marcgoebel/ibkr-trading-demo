"""Market data access: historical bars, snapshots, and live streaming."""

from __future__ import annotations

import logging
from typing import Callable, Dict

import pandas as pd
from ib_insync import IB, Contract, Forex, Stock, Ticker, util

logger = logging.getLogger(__name__)


class SymbolNotFoundError(Exception):
    """Raised when a contract for the given symbol cannot be qualified."""


class DataFeed:
    """Wraps ib_insync market data calls and returns clean pandas/dict structures."""

    def __init__(self, ib: IB) -> None:
        self.ib = ib

    def _resolve_contract(self, symbol: str) -> Contract:
        """Resolve a symbol string to a qualified IBKR contract.

        Forex pairs are detected by a ``/`` separator (e.g. ``EUR/USD``);
        anything else is treated as a US stock on SMART.
        """
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            contract: Contract = Forex(f"{base}{quote}")
        else:
            contract = Stock(symbol, "SMART", "USD")

        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise SymbolNotFoundError(f"Could not qualify contract for symbol '{symbol}'")
        return qualified[0]

    def get_historical_bars(
        self,
        symbol: str,
        duration: str = "2 D",
        bar_size: str = "5 mins",
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars and return them as a DataFrame.

        Args:
            symbol: Ticker (e.g. ``"AAPL"``) or forex pair (e.g. ``"EUR/USD"``).
            duration: IBKR duration string (e.g. ``"2 D"``, ``"1 W"``).
            bar_size: IBKR bar size (e.g. ``"5 mins"``, ``"1 hour"``).

        Returns:
            DataFrame with columns ``date, open, high, low, close, volume``.
        """
        contract = self._resolve_contract(symbol)
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES" if isinstance(contract, Stock) else "MIDPOINT",
            useRTH=True,
            formatDate=1,
        )
        if not bars:
            logger.warning("No historical bars returned for %s", symbol)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        df = util.df(bars)
        return df[["date", "open", "high", "low", "close", "volume"]]

    def get_snapshot(self, symbol: str) -> Dict[str, float]:
        """Return a one-shot snapshot of the latest market data for a symbol."""
        contract = self._resolve_contract(symbol)
        ticker = self.ib.reqMktData(contract, snapshot=True)
        # Wait briefly for the snapshot to populate.
        self.ib.sleep(2)
        snapshot = {
            "symbol": symbol,
            "last": ticker.last,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "volume": ticker.volume,
        }
        self.ib.cancelMktData(contract)
        return snapshot

    def stream_live_data(self, symbol: str, callback: Callable[[Ticker], None]) -> Ticker:
        """Subscribe to a live ticker and invoke ``callback`` on every update.

        The returned :class:`Ticker` can be used by the caller to cancel the
        subscription with ``ib.cancelMktData(ticker.contract)``.
        """
        contract = self._resolve_contract(symbol)
        ticker = self.ib.reqMktData(contract, "", False, False)
        ticker.updateEvent += callback
        logger.info("Live data stream started for %s", symbol)
        return ticker
