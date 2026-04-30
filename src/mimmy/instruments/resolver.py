from __future__ import annotations

from mimmy.core.types import Instrument, Ticker
from mimmy.markets import get_market


async def resolve(ticker: Ticker) -> list[Instrument]:
    """티커 하나 → 거래 대상 Instrument 목록.

    Mimmy의 핵심 전제: 이 목록 외의 어떤 것도 거래하지 않는다.
    """
    market = get_market(ticker.market)
    return await market.resolve_instruments(ticker)
