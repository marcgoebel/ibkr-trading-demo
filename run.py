"""CLI entry point for the IBKR trading demo."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

from bots.sma_crossover import SMACrossoverBot
from src.connection import ConnectionError as IBKRConnectError, IBKRConnection
from src.order_manager import OrderManager
from src.portfolio import Portfolio
from src.logger import TradeLogger
from src.risk_guard import RiskGuard


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _print_table(df, title: str) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("(no rows)")
    else:
        print(df.to_string(index=False))
    print()


def _mode_portfolio(ib) -> None:
    portfolio = Portfolio(ib)
    summary = portfolio.get_account_summary()
    positions = portfolio.get_positions()

    print("\n=== Account Summary ===")
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"  {key:<18} {value:>14,.2f}")
        else:
            print(f"  {key:<18} {value:>14}")
    _print_table(positions, "Open Positions")


def _mode_orders(ib, config) -> None:
    portfolio = Portfolio(ib)
    risk_guard = RiskGuard(config)
    trade_logger = TradeLogger(log_dir=config.get("logging", {}).get("log_dir", "logs"))
    order_manager = OrderManager(ib, risk_guard, portfolio, trade_logger)
    _print_table(order_manager.get_open_orders(), "Open Orders")


def _mode_trade(ib, config: Dict[str, Any], symbol: str) -> None:
    bot = SMACrossoverBot(ib, config)
    try:
        bot.run(symbol)
    except KeyboardInterrupt:
        bot.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="IBKR trading demo CLI")
    parser.add_argument(
        "--mode",
        required=True,
        choices=("portfolio", "orders", "trade"),
        help="What to do once connected.",
    )
    parser.add_argument("--symbol", default=None, help="Override the trading symbol from config.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    try:
        config = _load_config(config_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _setup_logging(config.get("logging", {}).get("level", "INFO"))
    log = logging.getLogger("run")

    conn_cfg = config.get("connection", {})
    symbol = args.symbol or config.get("trading", {}).get("symbol", "AAPL")

    try:
        with IBKRConnection(
            host=conn_cfg.get("host", "127.0.0.1"),
            port=int(conn_cfg.get("port", 7497)),
            client_id=int(conn_cfg.get("client_id", 1)),
        ) as ib:
            if args.mode == "portfolio":
                _mode_portfolio(ib)
            elif args.mode == "orders":
                _mode_orders(ib, config)
            elif args.mode == "trade":
                _mode_trade(ib, config, symbol)
    except IBKRConnectError as exc:
        log.error(
            "Could not reach TWS/Gateway at %s:%s — is it running and the API enabled?",
            conn_cfg.get("host"), conn_cfg.get("port"),
        )
        log.error("Details: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
