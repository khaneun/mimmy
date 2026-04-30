from __future__ import annotations

from datetime import datetime

from mimmy.core.types import Action, Instrument, InstrumentKind, MarketCode, Ticker
from mimmy.trading.broker import Fill
from mimmy.trading.portfolio import Portfolio


def _inst() -> Instrument:
    t = Ticker(market=MarketCode.KR, symbol="005930")
    return Instrument(ticker=t, kind=InstrumentKind.COMMON, symbol="005930")


def test_buy_then_sell_realizes_pnl():
    p = Portfolio()
    inst = _inst()
    p.apply(Fill(instrument=inst, side=Action.BUY, quantity=10, price=70_000,
                 filled_at=datetime.utcnow(), broker_order_id="1"))
    p.apply(Fill(instrument=inst, side=Action.SELL, quantity=5, price=72_000,
                 filled_at=datetime.utcnow(), broker_order_id="2"))
    pos = p.get(inst)
    assert pos is not None
    assert pos.quantity == 5
    assert pos.avg_price == 70_000
    assert pos.realized_pnl == (72_000 - 70_000) * 5
