"""Trade and event logging to CSV files plus stdlib logging."""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_TRADE_HEADER = (
    "timestamp", "symbol", "side", "quantity", "price", "order_type", "status"
)
_EVENT_HEADER = ("timestamp", "event_type", "message")


class TradeLogger:
    """Append trades and events to dated CSV files and stdlib logging."""

    def __init__(self, log_dir: str = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _trade_file(self, day: Optional[date] = None) -> Path:
        day = day or date.today()
        return self.log_dir / f"trades_{day.isoformat()}.csv"

    def _event_file(self, day: Optional[date] = None) -> Path:
        day = day or date.today()
        return self.log_dir / f"events_{day.isoformat()}.csv"

    def _append_row(self, path: Path, header: tuple, row: tuple) -> None:
        new_file = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(header)
            writer.writerow(row)

    def log_trade(
        self,
        timestamp: datetime,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_type: str,
        status: str,
    ) -> None:
        """Persist a single trade row to today's trade CSV."""
        row = (
            timestamp.isoformat(),
            symbol,
            side,
            quantity,
            price,
            order_type,
            status,
        )
        self._append_row(self._trade_file(), _TRADE_HEADER, row)
        logger.info(
            "TRADE %s %s %s @ %s [%s] status=%s",
            side, quantity, symbol, price, order_type, status,
        )

    def log_event(self, event_type: str, message: str) -> None:
        """Persist a non-trade event (CONNECT, DISCONNECT, SIGNAL, ERROR, ...)."""
        row = (datetime.now().isoformat(), event_type, message)
        self._append_row(self._event_file(), _EVENT_HEADER, row)
        logger.info("EVENT %s — %s", event_type, message)

    def get_todays_trades(self) -> pd.DataFrame:
        """Return today's trade log as a DataFrame (empty if no trades yet)."""
        path = self._trade_file()
        if not path.exists():
            return pd.DataFrame(columns=list(_TRADE_HEADER))
        return pd.read_csv(path)

    def get_todays_pnl(self) -> float:
        """Approximate realized P&L from today's trade rows.

        Uses signed-cash accounting: BUY counts as cash out, SELL as cash in.
        This is a rough approximation; for authoritative P&L use the broker
        figures returned by :meth:`Portfolio.get_pnl`.
        """
        trades = self.get_todays_trades()
        if trades.empty:
            return 0.0

        signed = trades.apply(
            lambda r: r["price"] * r["quantity"] * (1 if r["side"].upper() == "SELL" else -1),
            axis=1,
        )
        return float(signed.sum())
