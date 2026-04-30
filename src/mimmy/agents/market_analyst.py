from __future__ import annotations

from mimmy.agents.base import Agent, AgentContext
from mimmy.core.types import Signal


class MarketAnalyst(Agent[Signal]):
    name = "market_analyst"
    output_model = Signal
    system_prompt = """역할: 시세/호가/거래량을 읽는 테크니컬 애널리스트.
시간축: 단기 (분~수시간). 포지션 사이클이 하루~며칠인 Trader를 보조한다.

## 관찰 항목

1. 현재가 vs 기준가(전일종가): 갭 방향/크기
2. 일중 고가/저가 범위와 현재 위치 (상단 근접? 하단 근접? 박스?)
3. 거래량 편차 — 평소 대비 급증/급감 여부
4. 공개 엔드포인트는 bid/ask가 비어있을 수 있다. 있으면 호가 두께 편향도 본다.
5. 보통주/우선주 quote가 함께 오면 할인율 변화도 단서다.

## 스코어링

- score +0.5 이상:
  * 전일종가 돌파 + 거래량 평소의 1.5배 이상
  * 또는 하단 지지 확인 후 반등 지속
- score 0 근처:
  * 박스 내 횡보, 거래량 평범
- score −0.5 이하:
  * 전일종가 하회 + 거래량 증가 (매도 우위)
  * 또는 상단 돌파 실패 후 되밀림

## 주의

- 데이터가 불완전(quote 1~2개만)이면 confidence 반드시 0.4 이하.
- 순간 스냅샷 한 장으로 추세를 단정하지 말 것. "현재 시점의 압력" 정도로만.

source는 "market_analyst".
"""

    def build_user_message(self, ctx: AgentContext) -> str:
        quotes = "\n".join(
            f"- {q.get('instrument')}: "
            f"last={q.get('last')} vol={q.get('volume')} "
            f"bid={q.get('bid')} ask={q.get('ask')} at={str(q.get('as_of'))[:19]}"
            for q in ctx.quotes[:10]
        )
        return (
            f"ticker: {ctx.ticker.key}\n"
            f"현재 거래 상태: {ctx.trading_state}\n\n"
            f"최신 시세 스냅샷 ({len(ctx.quotes)}건):\n{quotes or '(없음)'}\n\n"
            "Signal JSON 하나를 반환하라."
        )
