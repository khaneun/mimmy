from __future__ import annotations

from datetime import datetime

from mimmy.core.types import Action, Instrument, Position
from mimmy.trading.broker import Fill


class Portfolio:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def get(self, instrument: Instrument) -> Position | None:
        return self._positions.get(instrument.key)

    def apply(self, fill: Fill) -> Position:
        key = fill.instrument.key
        pos = self._positions.get(key) or Position(instrument=fill.instrument)

        if fill.side == Action.BUY:
            new_qty = pos.quantity + fill.quantity
            pos.avg_price = (
                (pos.avg_price * pos.quantity + fill.price * fill.quantity) / new_qty
                if new_qty
                else 0.0
            )
            pos.quantity = new_qty
        elif fill.side == Action.SELL:
            realized = (fill.price - pos.avg_price) * min(fill.quantity, pos.quantity)
            pos.realized_pnl += realized
            pos.quantity -= fill.quantity

        pos.updated_at = datetime.utcnow()
        self._positions[key] = pos
        return pos
