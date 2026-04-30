"""미국 시장 어댑터. 데이터: polygon.io / EDGAR, 브로커: Alpaca / IBKR."""
from __future__ import annotations

from mimmy.core.types import Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.markets.base import Market


class USMarket(Market):
    code = MarketCode.US

    async def resolve_instruments(self, ticker: Ticker) -> list[Instrument]:
        # TODO: EDGAR에서 보통주/우선주 구분 (예: BRK.A vs BRK.B)
        # TODO: OCC에서 옵션 체인 조회
        # TODO: CME에서 선물 조회 (개별주 선물은 없지만 지수·섹터 선물 매핑 가능)
        return [
            Instrument(ticker=ticker, kind=InstrumentKind.COMMON, symbol=ticker.symbol),
        ]

    async def healthcheck(self) -> bool:
        return True
