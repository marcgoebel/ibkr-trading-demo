"""SMA crossover demo bot — illustrates the architecture, not a real strategy."""

from __future__ import annotations

import logging
import signal as signal_lib
import time
from typing import Optional

import pandas as pd
from ib_insync import IB

from src.data_feed import DataFeed
from src.logger import TradeLogger
from src.order_manager import OrderManager, OrderRejectedError
from src.portfolio import Portfolio
from src.risk_guard import RiskGuard

logger = logging.getLogger(__name__)

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"

# Map IBKR bar_size strings to a sleep interval (seconds) between cycles.
# A real implementation would schedule on bar close; sleep is fine for a demo.
_BAR_SIZE_SECONDS = {
    "1 min": 60,
    "5 mins": 300,
    "15 mins": 900,
    "30 mins": 1800,
    "1 hour": 3600,
}


class SMACrossoverBot:
    """Long-only SMA(fast) vs SMA(slow) crossover bot on a single symbol."""

    def __init__(self, ib: IB, config: dict) -> None:
        self.ib = ib
        self.config = config
        trading_cfg = config.get("trading", {})
        logging_cfg = config.get("logging", {})

        self.bar_size: str = trading_cfg.get("bar_size", "5 mins")
        self.duration: str = trading_cfg.get("duration", "2 D")
        self.sma_fast: int = int(trading_cfg.get("sma_fast", 20))
        self.sma_slow: int = int(trading_cfg.get("sma_slow", 50))
        self.order_quantity: float = float(trading_cfg.get("order_quantity", 10))

        self.data_feed = DataFeed(ib)
        self.portfolio = Portfolio(ib)
        self.trade_logger = TradeLogger(log_dir=logging_cfg.get("log_dir", "logs"))
        self.risk_guard = RiskGuard(config)
        self.order_manager = OrderManager(ib, self.risk_guard, self.portfolio, self.trade_logger)

        self._running = False
        self._symbol: Optional[str] = None

    @staticmethod
    def _detect_signal(bars: pd.DataFrame, fast: int, slow: int) -> str:
        """Return BUY / SELL / HOLD based on SMA crossover on the last two bars.

        A signal fires only on the bar where the crossover *happens* — i.e. the
        prior bar shows fast on one side of slow, and the latest bar shows it
        on the other. Bars where they are merely apart return HOLD. Strict
        inequalities are used to avoid flip-flops in flat markets.
        """
        if len(bars) < slow + 1:
            return SIGNAL_HOLD

        sma_fast = bars["close"].rolling(fast).mean()
        sma_slow = bars["close"].rolling(slow).mean()

        prev_fast, prev_slow = sma_fast.iloc[-2], sma_slow.iloc[-2]
        last_fast, last_slow = sma_fast.iloc[-1], sma_slow.iloc[-1]
        if pd.isna(prev_fast) or pd.isna(prev_slow):
            return SIGNAL_HOLD

        if prev_fast <= prev_slow and last_fast > last_slow:
            return SIGNAL_BUY
        if prev_fast >= prev_slow and last_fast < last_slow:
            return SIGNAL_SELL
        return SIGNAL_HOLD

    def _has_position(self, symbol: str) -> bool:
        positions = self.portfolio.get_positions()
        if positions.empty:
            return False
        match = positions[positions["symbol"] == symbol]
        return (not match.empty) and float(match.iloc[0]["quantity"]) != 0.0

    def _cycle(self, symbol: str) -> None:
        bars = self.data_feed.get_historical_bars(symbol, self.duration, self.bar_size)
        if bars.empty:
            logger.warning("No bars returned for %s — skipping cycle.", symbol)
            return

        sma_fast_val = bars["close"].rolling(self.sma_fast).mean().iloc[-1]
        sma_slow_val = bars["close"].rolling(self.sma_slow).mean().iloc[-1]
        last_close = bars["close"].iloc[-1]
        signal = self._detect_signal(bars, self.sma_fast, self.sma_slow)

        logger.info(
            "%s | last=%.2f | SMA%d=%.2f | SMA%d=%.2f | signal=%s",
            symbol, last_close, self.sma_fast, sma_fast_val,
            self.sma_slow, sma_slow_val, signal,
        )
        self.trade_logger.log_event("SIGNAL", f"{symbol} {signal} @ {last_close:.2f}")

        try:
            if signal == SIGNAL_BUY and not self._has_position(symbol):
                self.order_manager.buy(symbol, self.order_quantity, "MARKET")
            elif signal == SIGNAL_SELL and self._has_position(symbol):
                self.order_manager.close_position(symbol)
        except OrderRejectedError as exc:
            logger.warning("Order rejected by RiskGuard: %s", exc)

    def run(self, symbol: str) -> None:
        """Run the trading loop until :meth:`stop` is called or Ctrl+C."""
        self._symbol = symbol
        self._running = True
        signal_lib.signal(signal_lib.SIGINT, lambda *_: self.stop())

        sleep_seconds = _BAR_SIZE_SECONDS.get(self.bar_size, 300)
        logger.info(
            "SMA Crossover Bot started on %s (fast=%d, slow=%d, bar=%s)",
            symbol, self.sma_fast, self.sma_slow, self.bar_size,
        )
        self.trade_logger.log_event("BOT_START", f"{symbol} fast={self.sma_fast} slow={self.sma_slow}")

        while self._running:
            try:
                self._cycle(symbol)
            except Exception as exc:  # noqa: BLE001 - bot must survive transient errors
                logger.exception("Cycle failed: %s", exc)
                self.trade_logger.log_event("ERROR", str(exc))
            # Sleep in 1-second slices so stop() reacts quickly.
            for _ in range(sleep_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def stop(self) -> None:
        """Stop the loop and cancel any open orders."""
        if not self._running:
            return
        self._running = False
        try:
            cancelled = self.order_manager.cancel_all()
            if cancelled:
                logger.info("Cancelled open orders: %s", cancelled)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to cancel orders during stop: %s", exc)
        logger.info("SMA Crossover Bot stopped.")
        self.trade_logger.log_event("BOT_STOP", self._symbol or "")
