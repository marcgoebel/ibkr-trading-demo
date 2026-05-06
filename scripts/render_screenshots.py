"""Render the three Upwork-portfolio screenshots as PNGs.

Generates:
  docs/screenshots/trade.png        — simulated `python run.py --mode trade` log
  docs/screenshots/portfolio.png    — simulated `python run.py --mode portfolio`
  docs/screenshots/architecture.png — text architecture diagram

Run from the project root:  python scripts/render_screenshots.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple

from PIL import Image, ImageDraw, ImageFont

# ---------- Theme ----------------------------------------------------------

BG = (13, 17, 23)            # GitHub-dark
FG = (220, 223, 228)         # default text
FG_DIM = (139, 148, 158)     # dim chrome
COLOR_TIME = (121, 192, 255) # cyan-ish for timestamps
COLOR_INFO = (139, 148, 158) # gray for INFO
COLOR_LOGGER = (210, 168, 255)  # purple for module names
COLOR_BUY = (86, 211, 100)   # green
COLOR_SELL = (255, 123, 114) # red
COLOR_HOLD = (139, 148, 158) # gray
COLOR_HEADER = (255, 215, 90)  # yellow for "=== ... ==="
COLOR_NUMBER = (210, 168, 255)
COLOR_PROMPT = (86, 211, 100)
COLOR_CMD = (220, 223, 228)
COLOR_KEY = (121, 192, 255)
COLOR_WARN = (255, 215, 90)
COLOR_TITLE = (240, 246, 252)

FONT_PATH = "/System/Library/Fonts/Menlo.ttc"
SCALE = 2  # Render at 2x for retina-sharp screenshots
FONT_SIZE = 14 * SCALE
LINE_HEIGHT = 20 * SCALE
PAD_X = 28 * SCALE
PAD_Y = 22 * SCALE
TITLE_BAR_HEIGHT = 30 * SCALE


def _font(size: int = FONT_SIZE, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Menlo.ttc has Regular at index 0, Bold at index 1.
    return ImageFont.truetype(FONT_PATH, size, index=1 if bold else 0)


# ---------- Token-based line painter --------------------------------------

# Each "span" is (text, color). A line is a list of spans rendered left-to-right.
Span = Tuple[str, Tuple[int, int, int]]
Line = List[Span]


def _paint_log_line(line: str) -> Line:
    """Color a stdlib-formatted log line: 'TS | LEVEL | logger | msg'."""
    parts = line.split(" | ", 3)
    if len(parts) != 4:
        return [(line, FG)]
    ts, level, logger_name, msg = parts

    msg_color = FG
    if "TRADE BUY" in msg:
        msg_color = COLOR_BUY
    elif "TRADE SELL" in msg:
        msg_color = COLOR_SELL
    elif "signal=BUY" in msg:
        msg_color = COLOR_BUY
    elif "signal=SELL" in msg:
        msg_color = COLOR_SELL
    elif "signal=HOLD" in msg:
        msg_color = FG_DIM
    elif level.strip() == "WARNING":
        msg_color = COLOR_WARN

    spans: Line = [
        (ts, COLOR_TIME),
        (" | ", FG_DIM),
        (f"{level:<7}", COLOR_INFO if level.strip() == "INFO" else COLOR_WARN),
        (" | ", FG_DIM),
        (f"{logger_name:<22}", COLOR_LOGGER),
        (" | ", FG_DIM),
        (msg, msg_color),
    ]
    return spans


def _paint_plain(line: str) -> Line:
    """Color a non-log line (prompts, headers, tables)."""
    if line.startswith("$ "):
        return [("$ ", COLOR_PROMPT), (line[2:], COLOR_CMD)]
    if line.startswith("=== ") and line.endswith(" ==="):
        return [(line, COLOR_HEADER)]
    if line.startswith("^C"):
        return [(line, COLOR_WARN)]
    if line.startswith("Session realized P&L"):
        # color the value
        m = re.match(r"(.*?)([-+]?[\d.]+)( USD.*)", line)
        if m:
            num = m.group(2)
            num_color = COLOR_SELL if num.startswith("-") else COLOR_BUY
            return [(m.group(1), FG), (num, num_color), (m.group(3), FG)]
        return [(line, FG)]
    # Account summary key/value line
    m = re.match(r"^(\s+)(\S+)(\s{2,})([\d,.\-+]+)$", line)
    if m:
        return [(m.group(1), FG), (m.group(2), COLOR_KEY), (m.group(3), FG), (m.group(4), COLOR_NUMBER)]
    # Table header / rows — just render normally with slight dim for dashes
    if line.strip() == "":
        return [(" ", FG)]
    return [(line, FG)]


def _paint(line: str) -> Line:
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| ", line):
        return _paint_log_line(line)
    return _paint_plain(line)


# ---------- Renderer -------------------------------------------------------

def _measure_max_width(lines: Iterable[str], font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw) -> int:
    width = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        width = max(width, bbox[2] - bbox[0])
    return width


def _draw_title_bar(draw: ImageDraw.ImageDraw, width: int, title: str) -> None:
    draw.rectangle([(0, 0), (width, TITLE_BAR_HEIGHT)], fill=(33, 38, 45))
    # macOS-style traffic lights
    cx, cy = 18 * SCALE, TITLE_BAR_HEIGHT // 2
    r = 6 * SCALE
    for color, dx in (((255, 95, 86), 0), ((255, 189, 46), 20 * SCALE), ((39, 201, 63), 40 * SCALE)):
        draw.ellipse([(cx + dx - r, cy - r), (cx + dx + r, cy + r)], fill=color)
    title_font = _font(13 * SCALE, bold=False)
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) / 2, (TITLE_BAR_HEIGHT - (bbox[3] - bbox[1])) / 2 - 2 * SCALE),
              title, fill=FG_DIM, font=title_font)


def render(lines: List[str], output: Path, title: str) -> None:
    font = _font()
    # Provisional canvas just to measure
    probe = Image.new("RGB", (10, 10), BG)
    probe_draw = ImageDraw.Draw(probe)
    text_width_px = _measure_max_width(lines, font, probe_draw)

    width = text_width_px + PAD_X * 2
    height = TITLE_BAR_HEIGHT + PAD_Y * 2 + LINE_HEIGHT * len(lines)

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    _draw_title_bar(draw, width, title)

    y = TITLE_BAR_HEIGHT + PAD_Y
    for line in lines:
        spans = _paint(line)
        x = PAD_X
        for text, color in spans:
            draw.text((x, y), text, fill=color, font=font)
            bbox = draw.textbbox((0, 0), text, font=font)
            x += bbox[2] - bbox[0]
        y += LINE_HEIGHT

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG")
    print(f"  wrote {output}  ({width}x{height})")


# ---------- Content --------------------------------------------------------

TRADE_LINES: List[str] = [
    "$ python run.py --mode trade --symbol AAPL",
    "2026-05-02 14:29:58 | INFO    | src.connection         | Connecting to IBKR at 127.0.0.1:7497 (clientId=1, attempt 1/3)",
    "2026-05-02 14:29:58 | INFO    | src.connection         | Connected to IBKR.",
    "2026-05-02 14:29:59 | INFO    | bots.sma_crossover     | SMA Crossover Bot started on AAPL (fast=20, slow=50, bar=5 mins)",
    "2026-05-02 14:30:01 | INFO    | bots.sma_crossover     | AAPL | last=187.42 | SMA20=186.91 | SMA50=185.74 | signal=HOLD",
    "2026-05-02 14:35:02 | INFO    | bots.sma_crossover     | AAPL | last=187.66 | SMA20=187.02 | SMA50=185.78 | signal=HOLD",
    "2026-05-02 14:40:03 | INFO    | bots.sma_crossover     | AAPL | last=187.85 | SMA20=187.18 | SMA50=185.83 | signal=HOLD",
    "2026-05-02 14:45:02 | INFO    | bots.sma_crossover     | AAPL | last=188.21 | SMA20=187.34 | SMA50=185.89 | signal=HOLD",
    "2026-05-02 14:50:03 | INFO    | bots.sma_crossover     | AAPL | last=188.74 | SMA20=187.55 | SMA50=185.97 | signal=HOLD",
    "2026-05-02 14:55:02 | INFO    | bots.sma_crossover     | AAPL | last=189.18 | SMA20=187.80 | SMA50=186.07 | signal=HOLD",
    "2026-05-02 15:00:03 | INFO    | bots.sma_crossover     | AAPL | last=189.52 | SMA20=188.06 | SMA50=186.18 | signal=HOLD",
    "2026-05-02 15:05:02 | INFO    | bots.sma_crossover     | AAPL | last=189.71 | SMA20=188.31 | SMA50=186.31 | signal=BUY",
    "2026-05-02 15:05:04 | INFO    | src.logger             | TRADE BUY 10 AAPL @ 189.73 [MARKET] status=Filled",
    "2026-05-02 15:10:03 | INFO    | bots.sma_crossover     | AAPL | last=190.04 | SMA20=188.55 | SMA50=186.45 | signal=HOLD",
    "2026-05-02 15:15:02 | INFO    | bots.sma_crossover     | AAPL | last=190.32 | SMA20=188.78 | SMA50=186.59 | signal=HOLD",
    "2026-05-02 15:20:03 | INFO    | bots.sma_crossover     | AAPL | last=190.18 | SMA20=188.96 | SMA50=186.72 | signal=HOLD",
    "2026-05-02 15:25:02 | INFO    | bots.sma_crossover     | AAPL | last=189.84 | SMA20=189.10 | SMA50=186.85 | signal=HOLD",
    "2026-05-02 15:30:03 | INFO    | bots.sma_crossover     | AAPL | last=189.46 | SMA20=189.18 | SMA50=186.97 | signal=HOLD",
    "2026-05-02 15:35:02 | INFO    | bots.sma_crossover     | AAPL | last=189.02 | SMA20=189.20 | SMA50=187.07 | signal=HOLD",
    "2026-05-02 15:40:03 | INFO    | bots.sma_crossover     | AAPL | last=188.61 | SMA20=189.16 | SMA50=187.16 | signal=HOLD",
    "2026-05-02 15:45:02 | INFO    | bots.sma_crossover     | AAPL | last=188.04 | SMA20=189.05 | SMA50=187.22 | signal=HOLD",
    "2026-05-02 15:50:03 | INFO    | bots.sma_crossover     | AAPL | last=187.55 | SMA20=188.88 | SMA50=187.26 | signal=HOLD",
    "2026-05-02 15:55:02 | INFO    | bots.sma_crossover     | AAPL | last=187.18 | SMA20=188.66 | SMA50=187.28 | signal=HOLD",
    "2026-05-02 16:00:03 | INFO    | bots.sma_crossover     | AAPL | last=186.74 | SMA20=188.40 | SMA50=187.27 | signal=HOLD",
    "2026-05-02 16:05:02 | INFO    | bots.sma_crossover     | AAPL | last=186.41 | SMA20=188.10 | SMA50=187.24 | signal=SELL",
    "2026-05-02 16:05:04 | INFO    | src.logger             | TRADE SELL 10 AAPL @ 186.39 [MARKET] status=Filled",
    "2026-05-02 16:10:03 | INFO    | bots.sma_crossover     | AAPL | last=186.05 | SMA20=187.79 | SMA50=187.20 | signal=HOLD",
    "2026-05-02 16:15:02 | INFO    | bots.sma_crossover     | AAPL | last=185.82 | SMA20=187.46 | SMA50=187.13 | signal=HOLD",
    "^C",
    "2026-05-02 16:17:11 | INFO    | bots.sma_crossover     | SMA Crossover Bot stopped.",
    "2026-05-02 16:17:11 | INFO    | src.connection         | Disconnected from IBKR.",
    "",
    "Session realized P&L: -33.40 USD  (1 round-trip on AAPL)",
]

PORTFOLIO_LINES: List[str] = [
    "$ python run.py --mode portfolio",
    "2026-05-02 14:12:03 | INFO    | src.connection         | Connecting to IBKR at 127.0.0.1:7497 (clientId=1, attempt 1/3)",
    "2026-05-02 14:12:03 | INFO    | src.connection         | Connected to IBKR.",
    "",
    "=== Account Summary ===",
    "  NetLiquidation         102,847.55",
    "  TotalCashValue          54,210.18",
    "  UnrealizedPnL              312.40",
    "  BuyingPower            411,390.20",
    "",
    "=== Open Positions ===",
    " symbol  quantity  avg_cost  market_value  unrealized_pnl",
    "   AAPL        25    187.42       4790.50          105.00",
    "   MSFT        15    412.10       6201.45           20.95",
    "   NVDA        10    872.55       8847.20          121.70",
    "   TSLA         8    198.30       1612.40           24.80",
    " EURUSD     20000      1.0842   21712.00           40.00",
    "",
    "2026-05-02 14:12:05 | INFO    | src.connection         | Disconnected from IBKR.",
]

ARCHITECTURE_LINES: List[str] = [
    "                       +----------------------+",
    "                       |   config.yaml        |",
    "                       |   (limits & params)  |",
    "                       +----------+-----------+",
    "                                  | loaded once",
    "                                  v",
    "+---------------+   +--------------------------+   +----------------+",
    "|  IBKR TWS /   |<->|      IBKRConnection      |   |  TradeLogger   |",
    "|  IB Gateway   |   |  (auto-reconnect, ctx)   |   |  (CSV + stdlog)|",
    "+---------------+   +------------+-------------+   +--------^-------+",
    "                                 | ib_insync.IB             |",
    "              +------------------+-------------+            |",
    "              v                  v             v            |",
    "       +------------+    +--------------+  +------------+   |",
    "       | DataFeed   |    |  Portfolio   |  | RiskGuard  |   |",
    "       | (bars,     |    |  (positions, |  | (4 checks) |   |",
    "       |  ticks)    |    |   summary,   |  +-----+------+   |",
    "       +-----+------+    |   pnl)       |        |          |",
    "             |           +------+-------+        |          |",
    "             | DataFrame        | snapshot       | allow?   |",
    "             v                  v                v          |",
    "        +--------------------------------------------+      |",
    "        |         SMACrossoverBot                    |      |",
    "        |  bars -> SMA(fast/slow) -> crossover sig.  |      |",
    "        +---------------------+----------------------+      |",
    "                              | BUY / SELL                  |",
    "                              v                             |",
    "                    +---------------------+                 |",
    "                    |   OrderManager      |  log_trade()    |",
    "                    |   (risk-checked,    | --------------->|",
    "                    |    audited)         |                 |",
    "                    +----------+----------+                 |",
    "                               | placeOrder                 |",
    "                               v                            |",
    "                       +---------------+                    |",
    "                       |    IBKR       |  fill / status     |",
    "                       |   (broker)    | -------------------+",
    "                       +---------------+",
]


def main() -> None:
    out = Path("docs/screenshots")
    print("Rendering screenshots...")
    render(TRADE_LINES,        out / "trade.png",        "marc — bash — 130x40")
    render(PORTFOLIO_LINES,    out / "portfolio.png",    "marc — bash — 110x22")
    render(ARCHITECTURE_LINES, out / "architecture.png", "ibkr-trading-demo — architecture")
    print("Done.")


if __name__ == "__main__":
    main()
