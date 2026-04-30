"""뉴스 수집기 — 시장별 실제 소스로 디스패치."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from mimmy.core.types import MarketCode, Ticker


class NewsItem(BaseModel):
    ticker: Ticker
    headline: str
    url: str
    source: str
    published_at: datetime
    body: str | None = None


async def fetch_recent_news(ticker: Ticker, limit: int = 20) -> list[NewsItem]:
    if ticker.market == MarketCode.KR:
        from mimmy.data.sources.naver_finance import fetch_kr_news

        items = await fetch_kr_news(ticker, page_size=limit)
        return items[:limit]

    # TODO: US (Google News RSS / Benzinga), HK / CN
    return []
