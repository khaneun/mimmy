"""평가 루프 — 체결된 결정이 `evaluate_at_utc`에 도달하면
현재가를 조회해 Evaluator에게 넘기고, 나온 lesson을 저장한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Awaitable, Callable

from mimmy.agents.evaluator import Evaluator, EvaluatorInput
from mimmy.core.types import Decision, Instrument
from mimmy.logging import get_logger
from mimmy.runtime import store

log = get_logger(__name__)

PriceFetcher = Callable[[Instrument], Awaitable[float | None]]


def _compute_metrics(
    decision: Decision, entry_price: float, current_price: float
) -> tuple[float, float]:
    """(price_change_pct, realized_pnl) — BUY/SELL 방향을 반영."""
    if entry_price <= 0:
        return (0.0, 0.0)
    pct = (current_price - entry_price) / entry_price
    # BUY: 상승이 수익. SELL: 하락이 수익.
    sign = 1.0 if decision.action.value == "buy" else -1.0
    pnl = sign * decision.quantity * (current_price - entry_price)
    return (pct, pnl)


async def process_due_evaluations(
    price_fetcher: PriceFetcher,
    evaluator: Evaluator | None = None,
    now: datetime | None = None,
) -> list[int]:
    """평가 기한이 지난 결정을 모두 처리. 처리된 decision id 리스트 반환."""
    evaluator = evaluator or Evaluator()
    rows = store.pending_evaluations(now)
    processed: list[int] = []

    for row in rows:
        try:
            decision = Decision.model_validate_json(row.raw_json)
        except Exception as e:  # noqa: BLE001
            log.warning("eval_bad_raw_json", id=row.id, err=str(e))
            continue

        current_price = await price_fetcher(decision.instrument)
        if current_price is None or row.entry_price is None:
            log.warning(
                "eval_missing_price",
                id=row.id,
                has_current=current_price is not None,
                has_entry=row.entry_price is not None,
            )
            continue

        pct, pnl = _compute_metrics(decision, row.entry_price, current_price)

        horizon_min = 0
        if row.evaluate_at_utc and row.filled_at:
            horizon_min = int(
                (row.evaluate_at_utc - row.filled_at).total_seconds() / 60
            )

        try:
            out = await evaluator.evaluate(
                EvaluatorInput(
                    decision=decision,
                    realized_pnl=pnl,
                    horizon_minutes=horizon_min,
                    price_change_pct=pct,
                )
            )
        except Exception as e:  # noqa: BLE001
            log.exception("eval_llm_failed", id=row.id, err=str(e))
            continue

        store.mark_evaluated(
            decision_id=row.id,  # type: ignore[arg-type]
            score=out.score,
            lessons=out.lessons,
            ticker_key=row.ticker_key,
        )
        processed.append(row.id)  # type: ignore[arg-type]
        log.info(
            "eval_done",
            id=row.id,
            score=out.score,
            n_lessons=len(out.lessons),
            pct=round(pct, 4),
        )

    return processed
