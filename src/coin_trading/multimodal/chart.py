from __future__ import annotations

from pathlib import Path

from coin_trading.market_data.models import Candle

CHART_CANDLES = 120
CHART_WIDTH = 12
CHART_HEIGHT = 6
CHART_DPI = 100


def render_canonical_chart(candles: list[Candle], output: str | Path) -> Path:
    """Render a fixed-size, fixed-style candlestick and volume chart."""

    if len(candles) < CHART_CANDLES:
        raise ValueError(f"at least {CHART_CANDLES} confirmed candles are required")
    selected = candles[-CHART_CANDLES:]
    if any(not candle.confirmed for candle in selected):
        raise ValueError("chart requires confirmed candles only")

    import matplotlib  # Optional research dependency.

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (price_axis, volume_axis) = plt.subplots(
        2,
        1,
        figsize=(CHART_WIDTH, CHART_HEIGHT),
        dpi=CHART_DPI,
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05},
        sharex=True,
    )
    colors: list[str] = []
    for index, candle in enumerate(selected):
        opened = float(candle.open)
        closed = float(candle.close)
        color = "#16a085" if closed >= opened else "#c0392b"
        colors.append(color)
        price_axis.vlines(index, float(candle.low), float(candle.high), color=color, linewidth=1)
        body_bottom = min(opened, closed)
        body_height = max(abs(closed - opened), 1e-12)
        price_axis.add_patch(
            Rectangle((index - 0.3, body_bottom), 0.6, body_height, color=color)
        )
    volume_axis.bar(
        range(len(selected)),
        [float(candle.volume) for candle in selected],
        color=colors,
        width=0.6,
    )
    price_axis.grid(alpha=0.15)
    volume_axis.grid(alpha=0.15)
    price_axis.set_ylabel("Price")
    volume_axis.set_ylabel("Volume")
    volume_axis.set_xlabel(f"{selected[0].symbol} · {selected[0].interval}")
    figure.savefig(path, format="png", bbox_inches=None, metadata={"Software": "coin-trading"})
    plt.close(figure)
    return path
