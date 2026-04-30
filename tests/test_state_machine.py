from __future__ import annotations

from mimmy.trading.strategy import StateMachine, TradingState


def test_watching_can_go_anywhere():
    sm = StateMachine()
    assert sm.transition(TradingState.LONG)


def test_long_cannot_skip_to_implicit_short_states():
    sm = StateMachine()
    sm.transition(TradingState.LONG)
    assert TradingState.LONG not in sm.allowed_next()  # 같은 상태로 재전환 금지
    assert TradingState.SHORT in sm.allowed_next()
    assert TradingState.HEDGED in sm.allowed_next()
    assert TradingState.WATCHING in sm.allowed_next()
