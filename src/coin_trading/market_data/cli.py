from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from coin_trading.market_data.bybit import BybitRestClient
from coin_trading.market_data.storage import ImmutableJsonlStore


def _utc_milliseconds(value: str) -> int:
    try:
        if value.isdigit():
            return int(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use epoch milliseconds or an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("ISO-8601 timestamps must include a timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1_000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download validated Bybit V5 closed candles")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="60")
    parser.add_argument("--start", required=True, type=_utc_milliseconds)
    parser.add_argument("--end", required=True, type=_utc_milliseconds)
    parser.add_argument("--output", type=Path, default=Path("data/raw/bybit"))
    parser.add_argument("--testnet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candles = BybitRestClient(testnet=args.testnet).fetch_candles(
        symbol=args.symbol,
        interval=args.interval,
        start_ms=args.start,
        end_ms=args.end,
    )
    path = ImmutableJsonlStore(args.output).write_batch(
        dataset=f"candles_{args.interval}m",
        symbol=args.symbol,
        records=candles,
    )
    print(f"stored {len(candles)} validated candles in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
