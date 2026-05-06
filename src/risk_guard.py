"""Pre-trade risk checks driven by config.yaml limits."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Tuple

from .portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Hard limits loaded from the ``risk:`` section of config.yaml."""

    max_position_pct: float = 10.0
    max_open_positions: int = 5
    daily_loss_limit: float = 500.0
    min_buying_power: float = 1000.0


class RiskGuard:
    """Decide whether a candidate order is allowed.

    All checks are pre-trade. Order execution code MUST consult ``check()``
    and refuse to send the order when ``allowed`` is False.
    """

    def __init__(self, config: dict) -> None:
        risk_cfg = (config or {}).get("risk", {})
        self.limits = RiskLimits(
            max_position_pct=float(risk_cfg.get("max_position_pct", 10)),
            max_open_positions=int(risk_cfg.get("max_open_positions", 5)),
            daily_loss_limit=float(risk_cfg.get("daily_loss_limit", 500)),
            min_buying_power=float(risk_cfg.get("min_buying_power", 1000)),
        )

    def check(
        self,
        symbol: str,
        quantity: float,
        side: str,
        portfolio: Portfolio,
        estimated_price: float,
    ) -> Tuple[bool, str]:
        """Run all configured pre-trade checks and return ``(allowed, reason)``.

        Checks run in the order: daily loss → max open positions → buying
        power (BUY only) → max position size. The first failing check
        short-circuits and is logged at WARNING level.
        """
        side_upper = side.upper()
        notional = abs(quantity) * estimated_price

        summary = portfolio.get_account_summary()
        positions = portfolio.get_positions()
        pnl = portfolio.get_pnl()

        # 1. Daily loss limit — daily_pnl is negative on losing days.
        daily_pnl = pnl.get("daily_pnl") or 0.0
        if daily_pnl != daily_pnl:  # NaN guard
            daily_pnl = 0.0
        if daily_pnl <= -abs(self.limits.daily_loss_limit):
            reason = f"daily loss {daily_pnl:.2f} exceeds limit {self.limits.daily_loss_limit:.2f}"
            logger.warning("RiskGuard reject %s %s %s — %s", side_upper, quantity, symbol, reason)
            return False, reason

        # 2. Max open positions — only enforce when this order would open
        #    a NEW symbol. SELLs that reduce existing exposure are exempt.
        held_symbols = set(positions["symbol"].tolist()) if not positions.empty else set()
        opens_new = symbol not in held_symbols
        if opens_new and len(held_symbols) >= self.limits.max_open_positions:
            reason = (
                f"already holding {len(held_symbols)} positions "
                f"(limit {self.limits.max_open_positions})"
            )
            logger.warning("RiskGuard reject %s %s %s — %s", side_upper, quantity, symbol, reason)
            return False, reason

        # 3. Min buying power — only BUY orders consume buying power.
        if side_upper == "BUY":
            buying_power = float(summary.get("BuyingPower", 0.0))
            remaining = buying_power - notional
            if remaining < self.limits.min_buying_power:
                reason = (
                    f"buying power after trade {remaining:.2f} below "
                    f"minimum {self.limits.min_buying_power:.2f}"
                )
                logger.warning("RiskGuard reject %s %s %s — %s", side_upper, quantity, symbol, reason)
                return False, reason

        # 4. Max position size as percentage of net liquidation value.
        net_liq = float(summary.get("NetLiquidation", 0.0))
        if net_liq <= 0:
            reason = "no equity in account (NetLiquidation <= 0)"
            logger.warning("RiskGuard reject %s %s %s — %s", side_upper, quantity, symbol, reason)
            return False, reason
        position_pct = (notional / net_liq) * 100.0
        if position_pct > self.limits.max_position_pct:
            reason = (
                f"position size {position_pct:.2f}% exceeds limit "
                f"{self.limits.max_position_pct:.2f}%"
            )
            logger.warning("RiskGuard reject %s %s %s — %s", side_upper, quantity, symbol, reason)
            return False, reason

        return True, "OK"
