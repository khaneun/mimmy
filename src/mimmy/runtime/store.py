"""SQLite 기반 영속 저장소.

테이블:
- decisions : 실행/평가 대상이 되는 결정 (체결된 것만 저장)
- fills     : 체결 기록 (decisions과 1:1 유사, 다건체결 대비 별도 테이블)
- lessons   : Evaluator가 추출한 교훈 — Trader 프롬프트에 주입됨
- audit_log : self-edit 등 운영 이벤트
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Field, Session, SQLModel, create_engine, select

from mimmy.config import get_settings
from mimmy.core.types import Decision
from mimmy.trading.broker import Fill


# ─── 스키마 ───


class DecisionRow(SQLModel, table=True):
    __tablename__ = "decisions"
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    ticker_key: str = Field(index=True)
    action: str
    instrument_key: str
    quantity: float
    limit_price: float | None = None
    rationale: str
    raw_json: str

    # 체결 정보
    entry_price: float | None = None
    filled_at: datetime | None = None
    broker_order_id: str | None = None

    # 평가 스케줄/결과
    evaluate_at_utc: datetime | None = Field(default=None, index=True)
    evaluated_at: datetime | None = None
    eval_score: float | None = None
    eval_lessons_json: str | None = None  # list[str] as JSON


class LessonRow(SQLModel, table=True):
    __tablename__ = "lessons"
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    ticker_key: str = Field(index=True)
    text: str
    source_decision_id: int | None = Field(default=None, index=True)


class AuditLogRow(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    actor: str
    kind: str
    payload: str


class RuntimeSnapshotRow(SQLModel, table=True):
    """매 사이클 말미에 기록되는 포트폴리오·현금 스냅샷.

    대시보드는 이 테이블의 최신 행만 읽어 홈 화면을 구성한다.
    """
    __tablename__ = "runtime_snapshots"
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    ticker_key: str = Field(index=True)
    trading_state: str
    available_cash: float
    equity: float            # cash + 평가금액
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    paused: bool = False
    positions_json: str      # list[dict]
    last_quote_json: str | None = None  # 단일 티커 대표가 (보통주)


class AgentObservationRow(SQLModel, table=True):
    """한 사이클에서 각 에이전트가 방출한 의견/Signal/Decision 스냅샷.

    대시보드 Agents 탭 재료. DecisionRow 와 달리 '체결되지 않은 관찰'도 포함.
    """
    __tablename__ = "agent_observations"
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    ticker_key: str = Field(index=True)
    cycle_id: str = Field(index=True)  # 한 사이클 내 묶음용 (UUID or timestamp)
    agent: str                         # "news" / "disclosure" / "market" / "trader" / "risk"
    kind: str                          # "signal" / "decision" / "risk_gate"
    summary: str
    payload_json: str                  # 전체 직렬화


class RuntimeConfigRow(SQLModel, table=True):
    """대시보드가 토글하는 런타임 설정. 단일 행(id=1)으로 운용.

    루프가 각 사이클 초두에 읽어 반영한다. paper↔live 같이 재기동이 필요한
    항목은 `needs_restart=True` 로 플래그를 남긴다.
    """
    __tablename__ = "runtime_config"
    id: int | None = Field(default=1, primary_key=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    paused: bool = False
    ticker_market: str | None = None   # "KR"/"US"/"HK"/"CN" — None이면 env 기본값
    ticker_symbol: str | None = None
    broker: str | None = None          # "paper"/"kis"
    kis_env: str | None = None         # "paper"/"live"
    ai_provider: str | None = None     # "anthropic"/"openai"/"gemini"
    ai_model: str | None = None        # provider별 모델명 — 빈값이면 provider 기본값
    cycle_seconds: int | None = None
    eval_horizon_minutes: int | None = None
    needs_restart: bool = False


# ─── 엔진 ───


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().db_url, echo=False)
        SQLModel.metadata.create_all(_engine)
    return _engine


def session() -> Session:
    return Session(get_engine())


# ─── API ───


def record_filled_decision(decision: Decision, fill: Fill, horizon_minutes: int) -> DecisionRow:
    """체결된 결정을 저장하고 평가 시각을 예약한다."""
    evaluate_at = datetime.utcnow() + timedelta(minutes=horizon_minutes)
    row = DecisionRow(
        ticker_key=decision.instrument.ticker.key,
        action=decision.action.value,
        instrument_key=decision.instrument.key,
        quantity=decision.quantity,
        limit_price=decision.limit_price,
        rationale=decision.rationale,
        raw_json=decision.model_dump_json(),
        entry_price=fill.price,
        filled_at=fill.filled_at,
        broker_order_id=fill.broker_order_id,
        evaluate_at_utc=evaluate_at,
    )
    with session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def pending_evaluations(now: datetime | None = None) -> list[DecisionRow]:
    """평가 예약시각이 지났고 아직 평가되지 않은 결정들."""
    now = now or datetime.utcnow()
    with session() as s:
        stmt = (
            select(DecisionRow)
            .where(DecisionRow.evaluate_at_utc.is_not(None))
            .where(DecisionRow.evaluate_at_utc <= now)
            .where(DecisionRow.evaluated_at.is_(None))
            .order_by(DecisionRow.evaluate_at_utc)
        )
        return list(s.exec(stmt).all())


def mark_evaluated(
    decision_id: int, score: float, lessons: list[str], ticker_key: str
) -> None:
    now = datetime.utcnow()
    with session() as s:
        row = s.get(DecisionRow, decision_id)
        if row is None:
            return
        row.evaluated_at = now
        row.eval_score = score
        row.eval_lessons_json = json.dumps(lessons, ensure_ascii=False)
        s.add(row)
        for text in lessons:
            s.add(
                LessonRow(
                    ticker_key=ticker_key,
                    text=text,
                    source_decision_id=decision_id,
                )
            )
        s.commit()


def recent_lessons(ticker_key: str, limit: int = 20) -> list[str]:
    with session() as s:
        stmt = (
            select(LessonRow)
            .where(LessonRow.ticker_key == ticker_key)
            .order_by(LessonRow.created_at.desc())
            .limit(limit)
        )
        rows = list(s.exec(stmt).all())
    # 최신이 뒤로 가도록 뒤집는다 (프롬프트에서 "최근"이 마지막)
    rows.reverse()
    return [r.text for r in rows]


def recent_decisions(ticker_key: str, limit: int = 10) -> list[dict]:
    with session() as s:
        stmt = (
            select(DecisionRow)
            .where(DecisionRow.ticker_key == ticker_key)
            .order_by(DecisionRow.created_at.desc())
            .limit(limit)
        )
        rows = list(s.exec(stmt).all())
    rows.reverse()
    return [
        {
            "created_at": r.created_at.isoformat(),
            "action": r.action,
            "instrument_key": r.instrument_key,
            "quantity": r.quantity,
            "entry_price": r.entry_price,
            "eval_score": r.eval_score,
        }
        for r in rows
    ]


def log_audit(actor: str, kind: str, payload: dict) -> None:
    with session() as s:
        s.add(AuditLogRow(actor=actor, kind=kind, payload=json.dumps(payload, ensure_ascii=False)))
        s.commit()


def recent_audit(limit: int = 20) -> list[dict]:
    with session() as s:
        stmt = select(AuditLogRow).order_by(AuditLogRow.created_at.desc()).limit(limit)
        rows = list(s.exec(stmt).all())
    return [
        {
            "created_at": r.created_at.isoformat(),
            "actor": r.actor,
            "kind": r.kind,
            "payload": json.loads(r.payload) if r.payload else {},
        }
        for r in rows
    ]


# ─── 런타임 스냅샷 ───


def write_snapshot(
    *,
    ticker_key: str,
    trading_state: str,
    available_cash: float,
    equity: float,
    unrealized_pnl: float,
    realized_pnl: float,
    daily_pnl: float,
    paused: bool,
    positions: list[dict],
    last_quote: dict | None,
) -> None:
    row = RuntimeSnapshotRow(
        ticker_key=ticker_key,
        trading_state=trading_state,
        available_cash=available_cash,
        equity=equity,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
        daily_pnl=daily_pnl,
        paused=paused,
        positions_json=json.dumps(positions, ensure_ascii=False, default=str),
        last_quote_json=json.dumps(last_quote, ensure_ascii=False, default=str)
        if last_quote
        else None,
    )
    with session() as s:
        s.add(row)
        s.commit()


def latest_snapshot(ticker_key: str | None = None) -> dict | None:
    with session() as s:
        stmt = select(RuntimeSnapshotRow).order_by(RuntimeSnapshotRow.created_at.desc()).limit(1)
        if ticker_key:
            stmt = (
                select(RuntimeSnapshotRow)
                .where(RuntimeSnapshotRow.ticker_key == ticker_key)
                .order_by(RuntimeSnapshotRow.created_at.desc())
                .limit(1)
            )
        row = s.exec(stmt).first()
    if row is None:
        return None
    return {
        "created_at": row.created_at.isoformat(),
        "ticker_key": row.ticker_key,
        "trading_state": row.trading_state,
        "available_cash": row.available_cash,
        "equity": row.equity,
        "unrealized_pnl": row.unrealized_pnl,
        "realized_pnl": row.realized_pnl,
        "daily_pnl": row.daily_pnl,
        "paused": row.paused,
        "positions": json.loads(row.positions_json) if row.positions_json else [],
        "last_quote": json.loads(row.last_quote_json) if row.last_quote_json else None,
    }


def equity_series(ticker_key: str, limit: int = 50) -> list[dict]:
    """홈 스파크라인용 — 최근 N개 스냅샷의 (시각, equity)."""
    with session() as s:
        stmt = (
            select(RuntimeSnapshotRow)
            .where(RuntimeSnapshotRow.ticker_key == ticker_key)
            .order_by(RuntimeSnapshotRow.created_at.desc())
            .limit(limit)
        )
        rows = list(s.exec(stmt).all())
    rows.reverse()
    return [{"t": r.created_at.isoformat(), "equity": r.equity} for r in rows]


# ─── Agent 관측 ───


def write_observation(
    *,
    ticker_key: str,
    cycle_id: str,
    agent: str,
    kind: str,
    summary: str,
    payload: dict,
) -> None:
    with session() as s:
        s.add(
            AgentObservationRow(
                ticker_key=ticker_key,
                cycle_id=cycle_id,
                agent=agent,
                kind=kind,
                summary=summary,
                payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            )
        )
        s.commit()


def latest_cycle_observations(ticker_key: str) -> list[dict]:
    """가장 최근 cycle_id 에 속한 관측들을 반환 (에이전트별 의견 요약)."""
    with session() as s:
        # 가장 최근 cycle_id 찾기
        stmt_last = (
            select(AgentObservationRow.cycle_id)
            .where(AgentObservationRow.ticker_key == ticker_key)
            .order_by(AgentObservationRow.created_at.desc())
            .limit(1)
        )
        last = s.exec(stmt_last).first()
        if last is None:
            return []
        stmt = (
            select(AgentObservationRow)
            .where(AgentObservationRow.ticker_key == ticker_key)
            .where(AgentObservationRow.cycle_id == last)
            .order_by(AgentObservationRow.created_at)
        )
        rows = list(s.exec(stmt).all())
    return [
        {
            "created_at": r.created_at.isoformat(),
            "cycle_id": r.cycle_id,
            "agent": r.agent,
            "kind": r.kind,
            "summary": r.summary,
            "payload": json.loads(r.payload_json) if r.payload_json else {},
        }
        for r in rows
    ]


# ─── 런타임 설정 ───


def _config_row(s: Session) -> RuntimeConfigRow:
    row = s.get(RuntimeConfigRow, 1)
    if row is None:
        row = RuntimeConfigRow(id=1)
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def _serialize_config(row: RuntimeConfigRow) -> dict:
    return {
        "updated_at": row.updated_at.isoformat(),
        "paused": row.paused,
        "ticker_market": row.ticker_market,
        "ticker_symbol": row.ticker_symbol,
        "broker": row.broker,
        "kis_env": row.kis_env,
        "ai_provider": row.ai_provider,
        "ai_model": row.ai_model,
        "cycle_seconds": row.cycle_seconds,
        "eval_horizon_minutes": row.eval_horizon_minutes,
        "needs_restart": row.needs_restart,
    }


def get_runtime_config() -> dict:
    with session() as s:
        return _serialize_config(_config_row(s))


# 재기동이 필요한 키 — 프로세스 시작 시점에 한 번 바인딩되는 값들.
# AI provider/model 도 Orchestrator 인스턴스화 때 client가 결정되므로 여기 포함.
_RESTART_SENSITIVE = {
    "ticker_market",
    "ticker_symbol",
    "broker",
    "kis_env",
    "ai_provider",
    "ai_model",
    "cycle_seconds",
}


def update_runtime_config(patch: dict) -> dict:
    """허용 키만 덮어쓴다. 재기동이 필요한 키가 바뀌면 needs_restart=True."""
    allowed = {
        "paused",
        "ticker_market",
        "ticker_symbol",
        "broker",
        "kis_env",
        "ai_provider",
        "ai_model",
        "cycle_seconds",
        "eval_horizon_minutes",
    }
    with session() as s:
        row = _config_row(s)
        touched_restart = False
        for k, v in patch.items():
            if k not in allowed:
                continue
            before = getattr(row, k)
            if before != v:
                setattr(row, k, v)
                if k in _RESTART_SENSITIVE:
                    touched_restart = True
        if touched_restart:
            row.needs_restart = True
        row.updated_at = datetime.utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return _serialize_config(row)


def clear_needs_restart() -> None:
    with session() as s:
        row = _config_row(s)
        row.needs_restart = False
        s.add(row)
        s.commit()


def recent_news_cached(ticker_key: str, limit: int = 20) -> list[dict]:
    """대시보드용 최근 뉴스 — 관측 테이블에 저장된 news_analyst payload 재활용."""
    with session() as s:
        stmt = (
            select(AgentObservationRow)
            .where(AgentObservationRow.ticker_key == ticker_key)
            .where(AgentObservationRow.agent == "news")
            .order_by(AgentObservationRow.created_at.desc())
            .limit(limit)
        )
        rows = list(s.exec(stmt).all())
    out: list[dict] = []
    for r in rows:
        try:
            p = json.loads(r.payload_json)
        except Exception:  # noqa: BLE001
            continue
        for item in p.get("news_raw", []):
            out.append(item)
    return out[:limit]
