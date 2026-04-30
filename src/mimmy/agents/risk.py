"""Risk 게이트.

LLM에 맡기기엔 사고 날 수 있는 영역(포지션 한도, 최대 손실, 레버리지)은
결정론적 파이썬 규칙으로 먼저 막는다. 통과 후에만 브로커로 간다.
"""
from __future__ import annotations

from dataclasses import dataclass

from mimmy.core.types import Action, Decision


@dataclass
class RiskLimits:
    max_notional_per_trade: float = 5_000_000  # KRW
    max_daily_notional: float = 30_000_000
    max_open_positions: int = 4


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    decision: Decision | None


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self._daily_notional = 0.0
        self._open_positions = 0

    def evaluate(self, decision: Decision) -> RiskDecision:
        if decision.action == Action.HOLD:
            return RiskDecision(True, "hold", decision)

        notional = decision.quantity * (decision.limit_price or 0.0)
        if notional > self.limits.max_notional_per_trade:
            return RiskDecision(False, "trade notional too large", None)
        if self._daily_notional + notional > self.limits.max_daily_notional:
            return RiskDecision(False, "daily cap exceeded", None)
        if self._open_positions >= self.limits.max_open_positions and decision.action == Action.BUY:
            return RiskDecision(False, "too many open positions", None)

        return RiskDecision(True, "ok", decision)

    def record_fill(self, notional: float, side: Action) -> None:
        self._daily_notional += notional
        if side == Action.BUY:
            self._open_positions += 1
        elif side == Action.SELL and self._open_positions > 0:
            self._open_positions -= 1
