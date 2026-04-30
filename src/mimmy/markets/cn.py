"""중국 본토(SSE/SZSE) 시장 어댑터. 데이터: Tushare/AkShare, 브로커: 외국인 접근 제약 주의."""
from __future__ import annotations

from mimmy.core.types import Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.markets.base import Market


class CNMarket(Market):
    code = MarketCode.CN

    async def resolve_instruments(self, ticker: Ticker) -> list[Instrument]:
        return [
            Instrument(ticker=ticker, kind=InstrumentKind.COMMON, symbol=ticker.symbol),
        ]

    async def healthcheck(self) -> bool:
        return True
