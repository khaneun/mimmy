from __future__ import annotations

from abc import ABC, abstractmethod

from mimmy.core.types import Instrument, MarketCode, Ticker


class Market(ABC):
    """시장 어댑터. 각 시장별로 티커→상품 해석, 가격/공시 조회, 브로커 연결을 제공."""

    code: MarketCode

    @abstractmethod
    async def resolve_instruments(self, ticker: Ticker) -> list[Instrument]:
        """티커 하나에서 거래 가능한 관련 상품 전부를 반환.

        예) 삼성전자(005930) → 보통주, 우선주(005935), KOSPI 200 편입으로
            KOSPI 200 지수 옵션/선물, 삼성전자 개별주식선물·옵션 등.
        """

    @abstractmethod
    async def healthcheck(self) -> bool:
        """시장 데이터/브로커 연결이 살아있는지 확인."""
