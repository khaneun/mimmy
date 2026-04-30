"""한국(KRX) 시장 어댑터.

실제 데이터 소스:
- 공시: DART (dart.fss.or.kr) — open API key 필요
- 시세/호가: 네이버 금융 크롤링 또는 KIS/키움 OpenAPI
- 브로커: 키움 OpenAPI+ 또는 한국투자증권 OpenAPI

여기선 인터페이스와 대표 종목 몇 개의 관련 상품 테이블만 둔 스텁.
"""
from __future__ import annotations

from mimmy.core.types import Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.markets.base import Market

# 보통주 심볼 → 우선주 심볼 매핑 (확장 포인트)
_PREFERRED_MAP: dict[str, str] = {
    "005930": "005935",  # 삼성전자 / 삼성전자우
    "005380": "005385",  # 현대차 / 현대차우
    "051910": "051915",  # LG화학 / LG화학우
    "000660": "",        # SK하이닉스 (우선주 없음)
}


class KRMarket(Market):
    code = MarketCode.KR

    async def resolve_instruments(self, ticker: Ticker) -> list[Instrument]:
        out: list[Instrument] = [
            Instrument(ticker=ticker, kind=InstrumentKind.COMMON, symbol=ticker.symbol),
        ]

        pref = _PREFERRED_MAP.get(ticker.symbol)
        if pref:
            out.append(Instrument(ticker=ticker, kind=InstrumentKind.PREFERRED, symbol=pref))

        # TODO: 개별주식선물(KRX) 코드 조회 — 만기별 여러 건
        # TODO: 개별주식옵션 체인 조회 (콜/풋 × strike × expiry)
        # TODO: 관련 ETF (예: TIGER 반도체 등) — 티커 유사도 기반 탐색

        return out

    async def healthcheck(self) -> bool:
        # TODO: DART/KIS ping
        return True
