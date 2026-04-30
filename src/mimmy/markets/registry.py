from __future__ import annotations

from mimmy.core.types import MarketCode
from mimmy.markets.base import Market
from mimmy.markets.cn import CNMarket
from mimmy.markets.hk import HKMarket
from mimmy.markets.kr import KRMarket
from mimmy.markets.us import USMarket

_REGISTRY: dict[MarketCode, Market] = {
    MarketCode.KR: KRMarket(),
    MarketCode.US: USMarket(),
    MarketCode.HK: HKMarket(),
    MarketCode.CN: CNMarket(),
}


def get_market(code: MarketCode) -> Market:
    try:
        return _REGISTRY[code]
    except KeyError as e:
        raise ValueError(f"unsupported market: {code}") from e
