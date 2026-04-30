"""Evaluator — 실행된 Decision과 결과(pnl, 시간 경과 후 가격)를 짝지어 점수를 매기고
반복되는 실수/성공 패턴에서 '교훈(lesson)' 문장을 뽑아낸다.
다음 사이클부터 Trader 프롬프트의 `lessons`로 주입된다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from mimmy.agents.base import Agent, AgentContext
from mimmy.core.types import Decision


class EvaluatorInput(BaseModel):
    decision: Decision
    realized_pnl: float
    horizon_minutes: int
    price_change_pct: float


class EvaluatorOutput(BaseModel):
    score: float = Field(..., description="-1.0 (매우 나쁨) ~ +1.0 (매우 좋음)")
    lessons: list[str] = Field(
        default_factory=list,
        description="이번 결정에서 뽑은, 앞으로 피하거나 반복할 규칙 문장",
    )


class Evaluator(Agent[EvaluatorOutput]):
    name = "evaluator"
    output_model = EvaluatorOutput
    system_prompt = """역할: 사후 평가자(Post-trade reviewer).
목적: 방금 실행된 Decision과 결과(pnl, horizon 후 가격변동)를 읽고 교훈을 추출한다.

## 채점 원칙

- 결과 좋음 + 논리 좋음 → 높은 score. 교훈은 '반복하라' 로 표현.
- 결과 좋음 + 논리 나쁨(운) → score는 중립에 가깝게. 교훈에 "운이었다, 다음엔…" 명시.
- 결과 나쁨 + 논리 나쁨 → 강한 음의 score. 실패 원인 규칙화.
- 결과 나쁨 + 논리 좋음 → 음수 폭 완화. "논리는 유효하나 외생변수로 실패" 정리.

## lessons 작성법

- 각 문장은 **실행 가능한 규칙**이어야 한다.
  * 좋은 예: "강한 consensus 신호라도 변동성확대 국면이면 사이즈를 절반으로."
  * 나쁜 예: "조심해야 한다" (너무 일반적)
- 2~4개. 중복 금지. 이미 알려진 규칙은 재진술하지 말 것.
- 한 문장 30~60자.
"""

    def build_user_message(self, ctx: AgentContext) -> str:  # type: ignore[override]
        raise NotImplementedError("evaluate(input) 를 사용하라.")

    async def evaluate(self, inp: EvaluatorInput) -> EvaluatorOutput:
        user_msg = (
            f"## 실행된 결정\n{inp.decision.model_dump_json(indent=2)}\n\n"
            f"## 결과\n"
            f"- realized_pnl: {inp.realized_pnl}\n"
            f"- horizon: {inp.horizon_minutes}분\n"
            f"- 해당 instrument의 가격 변동: {inp.price_change_pct:+.2%}\n\n"
            f"위를 시스템 프롬프트의 채점 원칙대로 평가해 EvaluatorOutput JSON 하나를 반환하라."
        )
        return await self._call(user_msg, EvaluatorOutput)
