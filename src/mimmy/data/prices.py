"""시세/호가 피드 — 시장별 실제 소스로 디스패치."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from mimmy.core.types import Instrument, MarketCode


class Quote(BaseModel):
    instrument: Instrument
    bid: float | None
    ask: float | None
    last: float | None
    volume: float | None
    as_of: datetime


async def get_quote(instrument: Instrument) -> Quote | None:
    if instrument.ticker.market == MarketCode.KR:
        # 옵션·선물은 Naver 공개 엔드포인트에 없어서 보통주/우선주만.
        # 파생은 브로커(KIS/키움) 연결 이후 채움.
        from mimmy.data.sources.naver_finance import fetch_kr_quote

        return await fetch_kr_quote(instrument)

    # TODO: US (polygon / yfinance), HK (HKEX), CN (tushare)
    return None
