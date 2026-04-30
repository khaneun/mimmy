from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from mimmy.core.types import Action, Decision, Instrument


@dataclass
class Fill:
    instrument: Instrument
    side: Action
    quantity: float
    price: float
    filled_at: datetime
    broker_order_id: str


class Broker(ABC):
    @abstractmethod
    async def submit(self, decision: Decision) -> Fill:
        ...

    @abstractmethod
    async def cancel(self, broker_order_id: str) -> bool:
        ...


class PaperBroker(Broker):
    """체결 시뮬레이터. 가격은 limit_price(없으면 0)을 그대로 체결가로 사용한다.
    진짜 브로커 연결 전에 전체 파이프라인을 돌려보기 위한 더미."""

    def __init__(self) -> None:
        self._next_id = 1

    async def submit(self, decision: Decision) -> Fill:
        self._next_id += 1
        return Fill(
            instrument=decision.instrument,
            side=decision.action,
            quantity=decision.quantity,
            price=decision.limit_price or 0.0,
            filled_at=datetime.utcnow(),
            broker_order_id=f"paper-{self._next_id}",
        )

    async def cancel(self, broker_order_id: str) -> bool:
        return True
