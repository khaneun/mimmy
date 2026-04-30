"""기업 공시 수집기 — 시장별 실제 소스로 디스패치."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from mimmy.core.types import MarketCode, Ticker


class Disclosure(BaseModel):
    ticker: Ticker
    title: str
    url: str
    filed_at: datetime
    category: str  # "material-event", "periodic", "other"


async def fetch_recent_disclosures(ticker: Ticker, limit: int = 20) -> list[Disclosure]:
    if ticker.market == MarketCode.KR:
        from mimmy.data.sources.dart import fetch_kr_disclosures

        items = await fetch_kr_disclosures(ticker, page_count=limit)
        return items[:limit]

    # TODO: US (EDGAR), HK (HKEX), CN (cninfo)
    return []
