from __future__ import annotations

import pytest

from mimmy.core.types import InstrumentKind, MarketCode, Ticker
from mimmy.instruments import resolve


@pytest.mark.asyncio
async def test_kr_samsung_resolves_common_and_preferred():
    t = Ticker(market=MarketCode.KR, symbol="005930", name="삼성전자")
    insts = await resolve(t)
    kinds = {i.kind for i in insts}
    assert InstrumentKind.COMMON in kinds
    assert InstrumentKind.PREFERRED in kinds
    pref = next(i for i in insts if i.kind == InstrumentKind.PREFERRED)
    assert pref.symbol == "005935"


@pytest.mark.asyncio
async def test_kr_sk_hynix_no_preferred():
    t = Ticker(market=MarketCode.KR, symbol="000660", name="SK하이닉스")
    insts = await resolve(t)
    kinds = {i.kind for i in insts}
    assert kinds == {InstrumentKind.COMMON}


@pytest.mark.asyncio
async def test_us_returns_at_least_common():
    t = Ticker(market=MarketCode.US, symbol="AAPL")
    insts = await resolve(t)
    assert any(i.kind == InstrumentKind.COMMON for i in insts)
