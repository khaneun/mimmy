"""메인 거래 루프.

사이클마다:
1. runtime_config 확인 (paused면 주문 차단)
2. 기한이 지난 평가를 먼저 처리 (lessons 누적)
3. 최근 lessons/decisions 로드
4. 데이터 수집 → AgentContext → Orchestrator (agents 돌림)
5. 승인된 결정이 있으면 브로커로 주문 → Portfolio 갱신
6. 체결된 결정은 store에 영속화 + 평가 예약
7. 사이클 말미에 포트폴리오·현금 스냅샷 + 에이전트 관측 기록 (대시보드용)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from typing import Awaitable, Callable

from mimmy.agents.base import AgentContext
from mimmy.agents.orchestrator import CycleResult, Orchestrator
from mimmy.config import get_settings
from mimmy.core.types import Instrument, Ticker
from mimmy.data import disclosure as disclosure_mod
from mimmy.data import news as news_mod
from mimmy.data import prices as prices_mod
from mimmy.instruments import resolve
from mimmy.logging import get_logger
from mimmy.runtime import store
from mimmy.runtime.evaluator_loop import process_due_evaluations
from mimmy.trading import Broker, PaperBroker, Portfolio, StateMachine
from mimmy.trading.kis import KISBroker

log = get_logger(__name__)


def make_broker() -> Broker:
    s = get_settings()
    if s.broker == "kis":
        log.info("broker_selected", broker="kis", env=s.kis_env)
        return KISBroker()
    log.info("broker_selected", broker="paper")
    return PaperBroker()


def make_price_fetcher(broker: Broker) -> Callable[[Instrument], Awaitable[float | None]]:
    """Evaluator가 쓸 현재가 조회기.

    - KIS 브로커면 KIS inquire-price 사용 (가장 정확).
    - 아니면 Naver 공개 quote.
    """
    if isinstance(broker, KISBroker):

        async def _kis(inst: Instrument) -> float | None:
            return await broker.fetch_price(inst)

        return _kis

    async def _public(inst: Instrument) -> float | None:
        q = await prices_mod.get_quote(inst)
        return q.last if q else None

    return _public


async def build_context(
    ticker: Ticker,
    portfolio: Portfolio,
    state_machine: StateMachine,
    recent_decisions: list[dict],
    lessons: list[str],
    available_cash: float,
) -> tuple[AgentContext, list[dict], list[dict], list[dict]]:
    """Context + 원본 뉴스/공시/호가 (관측 기록용) 함께 반환."""
    instruments = await resolve(ticker)

    news_task = news_mod.fetch_recent_news(ticker)
    disc_task = disclosure_mod.fetch_recent_disclosures(ticker)
    quote_tasks = [prices_mod.get_quote(i) for i in instruments]

    news, disclosures, *quotes = await asyncio.gather(news_task, disc_task, *quote_tasks)

    news_raw = [n.model_dump(mode="json") for n in news]
    disc_raw = [d.model_dump(mode="json") for d in disclosures]
    quote_raw = [q.model_dump(mode="json") for q in quotes if q is not None]

    ctx = AgentContext(
        ticker=ticker,
        news=news_raw,
        disclosures=disc_raw,
        quotes=quote_raw,
        positions=[p.model_dump(mode="json") for p in portfolio.positions()],
        lessons=lessons,
        trading_state=state_machine.state.value,
        available_cash=available_cash,
        recent_decisions=recent_decisions,
    )
    return ctx, news_raw, disc_raw, quote_raw


def _compute_equity(
    available_cash: float, positions, last_price: float | None
) -> tuple[float, float]:
    """equity = cash + Σ(qty * last_price); unrealized = Σ(qty * (last - avg))."""
    if last_price is None:
        market_value = sum(p.quantity * p.avg_price for p in positions)
        unrealized = 0.0
    else:
        market_value = sum(p.quantity * last_price for p in positions)
        unrealized = sum(p.quantity * (last_price - p.avg_price) for p in positions)
    return available_cash + market_value, unrealized


def _record_observations(
    ticker_key: str,
    cycle_id: str,
    result: CycleResult,
    news_raw: list[dict],
    disc_raw: list[dict],
    quote_raw: list[dict],
) -> None:
    """각 에이전트의 의견 + 원본 뉴스/공시를 관측 테이블에 남긴다."""
    # 각 Signal 은 source 필드가 "news_analyst" 등.
    for sig in result.signals:
        agent = sig.source.replace("_analyst", "")  # news / disclosure / market
        payload = sig.model_dump(mode="json")
        # news 에이전트 payload에 원본 뉴스를 붙여 대시보드가 재사용
        if agent == "news":
            payload["news_raw"] = news_raw
        elif agent == "disclosure":
            payload["disclosures_raw"] = disc_raw
        elif agent == "market":
            payload["quotes_raw"] = quote_raw
        store.write_observation(
            ticker_key=ticker_key,
            cycle_id=cycle_id,
            agent=agent,
            kind="signal",
            summary=sig.rationale,
            payload=payload,
        )
    if result.decision is not None:
        store.write_observation(
            ticker_key=ticker_key,
            cycle_id=cycle_id,
            agent="trader",
            kind="decision",
            summary=result.decision.rationale,
            payload=result.decision.model_dump(mode="json"),
        )
    if result.risk is not None:
        store.write_observation(
            ticker_key=ticker_key,
            cycle_id=cycle_id,
            agent="risk",
            kind="risk_gate",
            summary=result.risk.reason,
            payload={"approved": result.risk.approved, "reason": result.risk.reason},
        )


async def run_loop(cycle_seconds: int = 60) -> None:
    settings = get_settings()
    ticker = Ticker(market=settings.market, symbol=settings.ticker)
    ticker_key = ticker.key

    orch = Orchestrator()
    broker = make_broker()
    price_fetcher = make_price_fetcher(broker)
    portfolio = Portfolio()
    state_machine = StateMachine()
    available_cash = settings.starting_cash
    starting_equity_today = settings.starting_cash
    today = date.today()

    log.info("loop_start", ticker=ticker_key, cycle_s=cycle_seconds, broker=settings.broker)

    while True:
        try:
            # 0) 런타임 설정 — paused 체크 + 대시보드 명령 소비
            rt_cfg = store.get_runtime_config()
            paused = bool(rt_cfg.get("paused"))
            await _consume_dashboard_commands(broker, portfolio)

            # 일자 변경 시 오늘 PnL 기준선 초기화
            if date.today() != today:
                today = date.today()
                starting_equity_today = available_cash + sum(
                    p.quantity * p.avg_price for p in portfolio.positions()
                )

            # 1) 기한이 지난 평가부터 소화
            processed = await process_due_evaluations(price_fetcher)
            if processed:
                log.info("evaluations_processed", count=len(processed))

            # 2) 최근 교훈 / 결정 로드 → 프롬프트 재료
            lessons = store.recent_lessons(ticker_key, limit=settings.eval_lessons_recent)
            recent = store.recent_decisions(ticker_key, limit=10)

            # 3) 컨텍스트 조립 + agents
            ctx, news_raw, disc_raw, quote_raw = await build_context(
                ticker, portfolio, state_machine,
                recent_decisions=recent,
                lessons=lessons,
                available_cash=available_cash,
            )
            cycle_id = uuid.uuid4().hex
            result = await orch.cycle(ctx)

            # 3b) 관측 기록 (대시보드용)
            _record_observations(ticker_key, cycle_id, result, news_raw, disc_raw, quote_raw)

            decision = result.approved
            # 4) 체결 — paused 상태면 주문을 건너뛴다 (포지션은 유지)
            if paused and decision and decision.action.value != "hold":
                store.log_audit(
                    "loop",
                    "order_skipped_paused",
                    {
                        "instrument": decision.instrument.key,
                        "action": decision.action.value,
                        "qty": decision.quantity,
                    },
                )
                log.info("order_skipped_paused", instrument=decision.instrument.key)
                decision = None

            if decision and decision.action.value != "hold":
                fill = await broker.submit(decision)

                if fill.quantity <= 0:
                    store.log_audit(
                        "loop",
                        "order_not_filled",
                        {
                            "instrument": fill.instrument.key,
                            "action": decision.action.value,
                            "requested_qty": decision.quantity,
                            "broker_order_id": fill.broker_order_id,
                        },
                    )
                    log.warning(
                        "order_not_filled",
                        instrument=fill.instrument.key,
                        requested_qty=decision.quantity,
                    )
                else:
                    if fill.quantity < decision.quantity:
                        log.warning(
                            "order_partial_fill",
                            instrument=fill.instrument.key,
                            requested=decision.quantity,
                            filled=fill.quantity,
                        )
                    portfolio.apply(fill)
                    sign = 1 if fill.side.value == "buy" else -1
                    available_cash -= sign * fill.quantity * fill.price

                    store.record_filled_decision(
                        decision, fill, horizon_minutes=settings.eval_horizon_minutes
                    )
                    log.info(
                        "order_filled",
                        instrument=fill.instrument.key,
                        qty=fill.quantity,
                        price=fill.price,
                        cash=available_cash,
                    )

            # 5) 스냅샷 기록 — 대시보드가 바로 읽는다
            last_price = None
            if quote_raw:
                # 보통주(첫번째 Instrument) 우선
                last_price = quote_raw[0].get("last")
            equity, unrealized = _compute_equity(
                available_cash, portfolio.positions(), last_price
            )
            realized = sum(p.realized_pnl for p in portfolio.positions())
            daily_pnl = equity - starting_equity_today
            store.write_snapshot(
                ticker_key=ticker_key,
                trading_state=state_machine.state.value,
                available_cash=available_cash,
                equity=equity,
                unrealized_pnl=unrealized,
                realized_pnl=realized,
                daily_pnl=daily_pnl,
                paused=paused,
                positions=[p.model_dump(mode="json") for p in portfolio.positions()],
                last_quote=(quote_raw[0] if quote_raw else None),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("loop_error", err=str(e))
            store.log_audit(
                "loop", "loop_error", {"err": str(e), "at": datetime.utcnow().isoformat()}
            )

        await asyncio.sleep(cycle_seconds)


async def _consume_dashboard_commands(broker: Broker, portfolio: Portfolio) -> None:
    """대시보드가 남긴 1회성 audit 명령(flatten_request 등)을 소비한다.

    실행 결과는 별도 audit(flatten_done)으로 남겨 재실행을 막는다.
    audit_log 를 메시지 큐 대용으로 쓰는 셈이라 깔끔하진 않지만,
    대시보드/루프 분리 프로세스 구조에서 가장 단순한 해법.
    """
    audits = store.recent_audit(limit=10)
    # 가장 최근부터 보는데, flatten_done 이 flatten_request 보다 먼저 나오면 이미 처리된 것.
    latest_request_at = None
    latest_done_at = None
    for a in audits:
        if a["kind"] == "flatten_request" and latest_request_at is None:
            latest_request_at = a["created_at"]
        elif a["kind"] == "flatten_done" and latest_done_at is None:
            latest_done_at = a["created_at"]
    if latest_request_at and (latest_done_at is None or latest_done_at < latest_request_at):
        results = await flatten_all(broker, portfolio)
        store.log_audit("loop", "flatten_done", {"results": results})


# 전량 청산 유틸 — 대시보드/텔레그램에서 호출
async def flatten_all(broker: Broker, portfolio: Portfolio) -> list[dict]:
    """보유 전량을 시장가로 청산. 반환: 청산 결과 요약 리스트."""
    from mimmy.core.types import Action, Decision

    results: list[dict] = []
    for pos in list(portfolio.positions()):
        if pos.quantity <= 0:
            continue
        decision = Decision(
            instrument=pos.instrument,
            action=Action.SELL,
            quantity=pos.quantity,
            limit_price=None,   # 시장가
            rationale="manual flatten from dashboard",
        )
        fill = await broker.submit(decision)
        if fill.quantity > 0:
            portfolio.apply(fill)
        results.append(
            {
                "instrument": pos.instrument.key,
                "requested": pos.quantity,
                "filled": fill.quantity,
                "price": fill.price,
            }
        )
        store.log_audit(
            "dashboard",
            "flatten",
            {
                "instrument": pos.instrument.key,
                "filled": fill.quantity,
                "price": fill.price,
            },
        )
    return results
