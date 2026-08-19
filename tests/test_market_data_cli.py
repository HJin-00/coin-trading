from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from coin_trading.market_data.cli import _utc_milliseconds, build_parser


def test_cli_accepts_utc_iso_timestamp() -> None:
    expected = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1_000)
    assert _utc_milliseconds("2026-01-01T00:00:00Z") == expected


def test_cli_rejects_naive_timestamp() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="timezone"):
        _utc_milliseconds("2026-01-01T00:00:00")


def test_cli_defaults_to_production_public_endpoint() -> None:
    args = build_parser().parse_args(["--start", "0", "--end", "60000"])
    assert not args.testnet
