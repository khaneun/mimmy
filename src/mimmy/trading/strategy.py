"""상태머신.

Mimmy의 전체 포지션이 어떤 '모드'에 있는지를 추적한다. Trader가 state를 바꾸는 의사결정을
낼 수 있고, Risk 레이어는 state 전환이 타당한지 한 번 더 본다.
"""
from __future__ import annotations

from enum import Enum

from mimmy.core.types import PositionState


class TradingState(str, Enum):
    WATCHING = "watching"   # 관망
    LONG = "long"           # 상승 배팅
    SHORT = "short"         # 하락 배팅 (풋/인버스)
    HEDGED = "hedged"       # 양방향 유지 (변동성 수익)


class StateMachine:
    def __init__(self) -> None:
        self.state = TradingState.WATCHING

    def allowed_next(self) -> set[TradingState]:
        # 모든 상태는 watching으로 되돌아갈 수 있다.
        base = {TradingState.WATCHING}
        if self.state == TradingState.WATCHING:
            return base | {TradingState.LONG, TradingState.SHORT, TradingState.HEDGED}
        if self.state == TradingState.LONG:
            return base | {TradingState.HEDGED, TradingState.SHORT}
        if self.state == TradingState.SHORT:
            return base | {TradingState.HEDGED, TradingState.LONG}
        if self.state == TradingState.HEDGED:
            return base | {TradingState.LONG, TradingState.SHORT}
        return base

    def transition(self, new: TradingState) -> bool:
        if new not in self.allowed_next():
            return False
        self.state = new
        return True

    @staticmethod
    def from_position_state(p: PositionState) -> TradingState:
        return {
            PositionState.FLAT: TradingState.WATCHING,
            PositionState.LONG: TradingState.LONG,
            PositionState.SHORT: TradingState.SHORT,
            PositionState.HEDGED: TradingState.HEDGED,
        }[p]
