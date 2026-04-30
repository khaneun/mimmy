"""홍콩(HKEX) 시장 어댑터. 데이터: HKEX, 브로커: Futu / IBKR."""
from __future__ import annotations

from mimmy.core.types import Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.markets.base import Market


class HKMarket(Market):
    code = MarketCode.HK

    async def resolve_instruments(self, ticker: Ticker) -> list[Instrument]:
        return [
            Instrument(ticker=ticker, kind=InstrumentKind.COMMON, symbol=ticker.symbol),
        ]

    async def healthcheck(self) -> bool:
        return True
