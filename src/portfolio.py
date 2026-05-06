"""Account and position views for the connected IBKR account."""

from __future__ import annotations

import logging
from typing import Dict

import pandas as pd
from ib_insync import IB

logger = logging.getLogger(__name__)

_SUMMARY_TAGS = ("NetLiquidation", "TotalCashValue", "UnrealizedPnL", "BuyingPower")


class Portfolio:
    """Read-only views over the connected account's positions and P&L."""

    def __init__(self, ib: IB) -> None:
        self.ib = ib

    def get_positions(self) -> pd.DataFrame:
        """Return open positions as a DataFrame.

        Columns: ``symbol, quantity, avg_cost, market_value, unrealized_pnl``.
        """
        positions = self.ib.positions()
        portfolio_items = {item.contract.conId: item for item in self.ib.portfolio()}

        rows = []
        for pos in positions:
            item = portfolio_items.get(pos.contract.conId)
            rows.append(
                {
                    "symbol": pos.contract.symbol,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                    "market_value": item.marketValue if item else None,
                    "unrealized_pnl": item.unrealizedPNL if item else None,
                }
            )
        return pd.DataFrame(
            rows,
            columns=["symbol", "quantity", "avg_cost", "market_value", "unrealized_pnl"],
        )

    def get_account_summary(self) -> Dict[str, float]:
        """Return key account metrics as a dict."""
        summary = self.ib.accountSummary()
        result: Dict[str, float] = {}
        for row in summary:
            if row.tag in _SUMMARY_TAGS:
                try:
                    result[row.tag] = float(row.value)
                except ValueError:
                    result[row.tag] = row.value
        return result

    def get_pnl(self) -> Dict[str, float]:
        """Return today's and total unrealized/realized P&L as a dict."""
        account = self.ib.managedAccounts()[0] if self.ib.managedAccounts() else ""
        pnl = self.ib.reqPnL(account)
        # ib_insync needs a brief moment to populate the PnL object.
        self.ib.sleep(1)
        return {
            "daily_pnl": pnl.dailyPnL,
            "unrealized_pnl": pnl.unrealizedPnL,
            "realized_pnl": pnl.realizedPnL,
        }
