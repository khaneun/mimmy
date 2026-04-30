from __future__ import annotations

from mimmy.agents.risk import RiskLimits, RiskManager
from mimmy.core.types import Action, Decision, Instrument, InstrumentKind, MarketCode, Ticker


def _decision(qty: float, price: float, action: Action = Action.BUY) -> Decision:
    t = Ticker(market=MarketCode.KR, symbol="005930")
    inst = Instrument(ticker=t, kind=InstrumentKind.COMMON, symbol="005930")
    return Decision(
        instrument=inst,
        action=action,
        quantity=qty,
        limit_price=price,
        rationale="test",
    )


def test_hold_always_passes():
    rm = RiskManager()
    g = rm.evaluate(_decision(10, 70_000, Action.HOLD))
    assert g.approved


def test_single_trade_cap():
    rm = RiskManager(RiskLimits(max_notional_per_trade=1_000_000))
    g = rm.evaluate(_decision(10, 200_000))  # 2,000,000 > 1,000,000
    assert not g.approved


def test_daily_cap_accumulates():
    rm = RiskManager(RiskLimits(max_notional_per_trade=10_000_000, max_daily_notional=5_000_000))
    rm.record_fill(notional=3_000_000, side=Action.BUY)
    g = rm.evaluate(_decision(30, 100_000))  # 3,000,000
    assert not g.approved
