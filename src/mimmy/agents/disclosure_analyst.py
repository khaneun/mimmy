from __future__ import annotations

from mimmy.agents.base import Agent, AgentContext
from mimmy.core.types import Signal


class DisclosureAnalyst(Agent[Signal]):
    name = "disclosure_analyst"
    output_model = Signal
    system_prompt = """역할: 공시 문서(DART/EDGAR 등)를 읽는 시니어 리서처.
목적: 최근 공시의 주가 영향을 수치화한 Signal 하나를 반환한다.

## 재료 강도 (category 기준)

- material-event (강한 재료):
  * 유상증자/무상증자   — 증자 규모와 목적에 따라 ±
  * 감자               — 방향은 상황 의존이지만 이벤트 자체가 크다
  * 자기주식 취득/처분 — 취득은 +, 처분/소각이 아니라면 −
  * 대량보유(5%) 변동  — 주체가 누구인지(기관/경영권분쟁) 중요
  * 합병/분할/영업양수도 — 프리미엄/디스카운트 방향
  * 최대주주/경영권 분쟁 — 변동성 급증
  * 회사채/CB/BW 발행   — 규모 크면 희석 우려로 −

- periodic (정기보고서):
  * 실적 컨센 대비 delta 로 해석. 수치 직접 비교 가능하면 score 강하게,
    단순 '보고서 제출'만 공시되면 score≈0.

- other:
  * 대부분 score=0 근처. 확신 낮춤.

## 출력 스케일

score: -1.0 ~ +1.0 (방향×강도)
confidence: 0~1 (문서의 구체성, 수치 명시성, 시장 영향력 기준)

## rationale
2~3건의 결정적 공시를 구체 명사(예: "자사주 3,000억 취득 공시") 로 짧게 적는다.

source는 "disclosure_analyst" 로 고정.
"""

    def build_user_message(self, ctx: AgentContext) -> str:
        items = "\n".join(
            f"- [{d.get('category')}] {d.get('title')} ({str(d.get('filed_at'))[:10]})"
            for d in ctx.disclosures[:30]
        )
        return (
            f"ticker: {ctx.ticker.key}\n"
            f"현재 거래 상태: {ctx.trading_state}\n\n"
            f"최근 2주 공시 ({len(ctx.disclosures)}건):\n{items or '(없음)'}\n\n"
            "Signal JSON 하나를 반환하라."
        )
