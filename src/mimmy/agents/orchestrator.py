"""Orchestrator — 한 사이클에서 analyst들을 병렬로 돌리고, trader→risk→broker로 넘긴다.

대시보드가 에이전트별 의견을 보여줘야 하므로, cycle() 은 최종 Decision 외에
각 단계의 출력(Signals, Decision, RiskGate)도 구조화해서 함께 돌려준다.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from mimmy.agents.base import AgentContext
from mimmy.agents.disclosure_analyst import DisclosureAnalyst
from mimmy.agents.market_analyst import MarketAnalyst
from mimmy.agents.news_analyst import NewsAnalyst
from mimmy.agents.risk import RiskDecision, RiskManager
from mimmy.agents.trader import Trader
from mimmy.core.types import Decision, Signal
from mimmy.logging import get_logger

log = get_logger(__name__)


@dataclass
class CycleResult:
    """한 사이클의 전체 산출물. 대시보드·루프가 공유."""

    signals: list[Signal] = field(default_factory=list)
    decision: Decision | None = None
    risk: RiskDecision | None = None
    approved: Decision | None = None   # risk 통과 후 최종 (hold 포함)

    def agent_summaries(self) -> list[dict[str, Any]]:
        """대시보드 Agents 탭에 바로 쓰는 요약 리스트."""
        out: list[dict[str, Any]] = []
        for sig in self.signals:
            out.append(
                {
                    "agent": sig.source,
                    "kind": "signal",
                    "score": sig.score,
                    "confidence": sig.confidence,
                    "summary": sig.rationale,
                    "payload": sig.model_dump(mode="json"),
                }
            )
        if self.decision is not None:
            out.append(
                {
                    "agent": "trader",
                    "kind": "decision",
                    "action": self.decision.action.value,
                    "quantity": self.decision.quantity,
                    "limit_price": self.decision.limit_price,
                    "summary": self.decision.rationale,
                    "payload": self.decision.model_dump(mode="json"),
                }
            )
        if self.risk is not None:
            out.append(
                {
                    "agent": "risk",
                    "kind": "risk_gate",
                    "approved": self.risk.approved,
                    "summary": self.risk.reason,
                    "payload": {"approved": self.risk.approved, "reason": self.risk.reason},
                }
            )
        return out


class Orchestrator:
    def __init__(self) -> None:
        self.news = NewsAnalyst()
        self.disc = DisclosureAnalyst()
        self.mkt = MarketAnalyst()
        self.trader = Trader()
        self.risk = RiskManager()

    async def cycle(self, ctx: AgentContext) -> CycleResult:
        signals: list[Signal] = list(
            await asyncio.gather(
                self.news.run(ctx),
                self.disc.run(ctx),
                self.mkt.run(ctx),
            )
        )
        log.info("signals_gathered", count=len(signals))

        decision = await self.trader.decide(ctx, signals)
        log.info(
            "trader_decision",
            action=decision.action.value,
            instrument=decision.instrument.key,
            qty=decision.quantity,
        )

        gate = self.risk.evaluate(decision)
        result = CycleResult(signals=signals, decision=decision, risk=gate)
        if gate.approved:
            result.approved = decision
        else:
            log.warning("risk_blocked", reason=gate.reason)
        return result
