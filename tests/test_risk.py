from decimal import Decimal

from test_config import safe_settings

from coin_trading.domain import AccountState, Side, TradeProposal
from coin_trading.risk import RiskEngine


def test_position_is_sized_by_loss_at_stop() -> None:
    engine = RiskEngine(safe_settings())
    proposal = TradeProposal(
        symbol="BTCUSDT",
        side=Side.LONG,
        entry_price=Decimal("50000"),
        stop_price=Decimal("47500"),
    )
    account = AccountState(equity=Decimal("10000000"), daily_pnl=Decimal("0"), open_positions=0)

    decision = engine.evaluate(proposal, account)

    assert decision.approved
    assert decision.quantity == Decimal("40")
    assert decision.notional == Decimal("2000000")


def test_missing_stop_is_rejected() -> None:
    decision = RiskEngine(safe_settings()).evaluate(
        TradeProposal("BTCUSDT", Side.LONG, Decimal("50000"), None),
        AccountState(Decimal("10000000"), Decimal("0"), 0),
    )
    assert not decision.approved
    assert "stop" in decision.reason


def test_daily_loss_limit_blocks_new_trade() -> None:
    decision = RiskEngine(safe_settings()).evaluate(
        TradeProposal("BTCUSDT", Side.SHORT, Decimal("50000"), Decimal("51000")),
        AccountState(Decimal("10000000"), Decimal("-300000"), 0),
    )
    assert not decision.approved
    assert "daily loss" in decision.reason


def test_invalid_stop_side_is_rejected() -> None:
    decision = RiskEngine(safe_settings()).evaluate(
        TradeProposal("BTCUSDT", Side.SHORT, Decimal("50000"), Decimal("49000")),
        AccountState(Decimal("10000000"), Decimal("0"), 0),
    )
    assert not decision.approved
    assert "short stop" in decision.reason
