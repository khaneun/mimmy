from __future__ import annotations

from mimmy.core.types import Action, Decision, Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.runtime.evaluator_loop import _compute_metrics


def _decision(action: Action, qty: float = 10) -> Decision:
    t = Ticker(market=MarketCode.KR, symbol="005930")
    inst = Instrument(ticker=t, kind=InstrumentKind.COMMON, symbol="005930")
    return Decision(
        instrument=inst,
        action=action,
        quantity=qty,
        limit_price=70_000,
        rationale="test",
    )


def test_buy_price_up_is_positive_pnl():
    pct, pnl = _compute_metrics(_decision(Action.BUY), entry_price=70_000, current_price=72_000)
    assert pct == pytest_approx(2_000 / 70_000)
    assert pnl == 10 * (72_000 - 70_000)


def test_buy_price_down_is_negative_pnl():
    _, pnl = _compute_metrics(_decision(Action.BUY), entry_price=70_000, current_price=68_000)
    assert pnl < 0


def test_sell_price_down_is_positive_pnl():
    """매도 결정은 가격이 내려갔을 때 좋은 결정이다."""
    _, pnl = _compute_metrics(_decision(Action.SELL), entry_price=70_000, current_price=68_000)
    assert pnl > 0


def test_sell_price_up_is_negative_pnl():
    _, pnl = _compute_metrics(_decision(Action.SELL), entry_price=70_000, current_price=72_000)
    assert pnl < 0


def test_zero_entry_price_safe():
    pct, pnl = _compute_metrics(_decision(Action.BUY), entry_price=0, current_price=1000)
    assert pct == 0.0
    assert pnl == 0.0


# 작은 pytest.approx 폴리필 (pytest 미설치 환경에서도 이 파일 자체는 import 가능하게)
try:
    import pytest

    pytest_approx = pytest.approx
except ImportError:  # pragma: no cover
    def pytest_approx(x: float, rel: float = 1e-6):
        class _A:
            def __eq__(self, other): return abs(other - x) <= rel * max(abs(x), 1)
        return _A()
