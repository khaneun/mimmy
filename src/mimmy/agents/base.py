"""LLM Agent 공통 기반.

provider 중립 — Anthropic / OpenAI / Gemini 어느 쪽이든 동일한 Agent 추상으로
구조화 출력(JSON)을 받아 Pydantic 모델로 검증한다.
실제 호출은 `mimmy.agents.llm.LLMClient` 가 담당.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from mimmy.agents.llm import LLMClient, make_llm_client
from mimmy.core.types import Ticker
from mimmy.logging import get_logger

log = get_logger(__name__)

TOut = TypeVar("TOut", bound=BaseModel)


@dataclass
class AgentContext:
    """단일 사이클에서 모든 에이전트가 공유하는 입력."""

    ticker: Ticker
    news: list[dict[str, Any]] = field(default_factory=list)
    disclosures: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)

    # 확장 필드 — Trader의 포지션·자금 인식용
    trading_state: str = "watching"        # TradingState 값
    available_cash: float = 0.0
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)


class Agent(ABC, Generic[TOut]):
    """구조화 출력(JSON)을 생성하는 Agent 추상."""

    name: str
    system_prompt: str
    output_model: type[TOut]

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or make_llm_client()

    @abstractmethod
    def build_user_message(self, ctx: AgentContext) -> str:
        ...

    async def run(self, ctx: AgentContext) -> TOut:
        user_msg = self.build_user_message(ctx)
        return await self._call(user_msg, self.output_model)

    async def _call(self, user_msg: str, output_model: type[TOut]) -> TOut:
        schema = output_model.model_json_schema()
        text = await self._client.complete_json(
            system=self.system_prompt,
            user=user_msg,
            schema=schema,
        )
        payload = _extract_json(text)
        return output_model.model_validate(payload)


def _extract_json(text: str) -> Any:
    """LLM 출력에서 첫 번째 JSON 객체를 뽑아낸다 (```json ``` 감싸기 허용)."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().startswith("json"):
            s = s.split("json", 1)[1]
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"agent returned no JSON object: {text[:200]!r}")
    return json.loads(s[start : end + 1])
