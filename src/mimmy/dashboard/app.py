"""모바일 대시보드 — FastAPI + 정적 SPA.

설계 요약:
- 모든 '현재 상태'는 runtime_snapshots 테이블의 최신 행에서 읽는다.
  (루프가 매 사이클 기록함 — 대시보드 프로세스는 read-only)
- '수동 액션' (pause/resume, flatten, restart, settings 변경) 은 DB에 플래그를
  쓰거나 서브프로세스를 호출한다.
- 챗은 self_edit.pipeline.propose_change 를 호출 (기존 동작 유지).
- 인증은 기본 OFF (내부망/터널 가정). TELEGRAM 권한 목록과 동일한 set을
  X-Mimmy-User 헤더로 강제하고 싶으면 MIMMY_DASHBOARD_REQUIRE_AUTH=true.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mimmy.config import get_settings
from mimmy.logging import get_logger
from mimmy.runtime import store

log = get_logger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


# ─── 요청 모델 ───


class ChatMessage(BaseModel):
    text: str
    user_id: str


class ChatResponse(BaseModel):
    reply: str
    artifact_url: str | None = None


class SettingsPatch(BaseModel):
    paused: bool | None = None
    ticker_market: str | None = None
    ticker_symbol: str | None = None
    broker: str | None = None        # "paper" | "kis"
    kis_env: str | None = None       # "paper" | "live"
    ai_provider: str | None = None   # "anthropic" | "openai" | "gemini"
    ai_model: str | None = None      # provider별 모델명 (빈값이면 provider 기본값)
    cycle_seconds: int | None = None
    eval_horizon_minutes: int | None = None


class FlattenRequest(BaseModel):
    confirm: str  # 'FLATTEN' 을 정확히 보내야 한다 (live 모드 안전장치)


class RestartRequest(BaseModel):
    confirm: str  # 'RESTART' 을 정확히 보내야 한다


# ─── 권한 ───


def _check_auth(request: Request) -> None:
    """헤더 X-Mimmy-User 가 AUTHORIZED_TELEGRAM_IDS 에 있어야 통과.

    설정이 비어 있으면 통과(개발 모드). 운영에선 반드시 채워둘 것.
    """
    s = get_settings()
    allowed = s.authorized_ids
    if not allowed:
        return
    raw = request.headers.get("x-mimmy-user", "")
    try:
        uid = int(raw)
    except ValueError:
        raise HTTPException(401, "missing or invalid X-Mimmy-User")
    if uid not in allowed:
        raise HTTPException(403, "unauthorized")


# ─── API ───


def create_app() -> FastAPI:
    app = FastAPI(title="Mimmy Dashboard", version="0.0.1")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # ── 홈: 잔고 + 포지션 + 상태 + 오늘 PnL + 스파크라인 ──
    @app.get("/api/home")
    def api_home() -> dict[str, Any]:
        s = get_settings()
        ticker_key = f"{s.market.value}:{s.ticker}"
        snap = store.latest_snapshot(ticker_key)
        series = store.equity_series(ticker_key, limit=60)
        cfg = store.get_runtime_config()
        return {
            "ticker": {
                "market": s.market.value,
                "symbol": s.ticker,
                "key": ticker_key,
            },
            "broker": s.broker,
            "kis_env": s.kis_env,
            "paused": cfg.get("paused") or (snap["paused"] if snap else False),
            "needs_restart": cfg.get("needs_restart", False),
            "snapshot": snap,
            "equity_series": series,
        }

    # ── 시세·뉴스·공시 탭 ──
    @app.get("/api/market")
    def api_market() -> dict[str, Any]:
        s = get_settings()
        ticker_key = f"{s.market.value}:{s.ticker}"
        snap = store.latest_snapshot(ticker_key)
        obs = store.latest_cycle_observations(ticker_key)

        news: list[dict] = []
        disclosures: list[dict] = []
        quote = snap.get("last_quote") if snap else None
        for o in obs:
            p = o.get("payload") or {}
            if o["agent"] == "news":
                news = p.get("news_raw", []) or news
            elif o["agent"] == "disclosure":
                disclosures = p.get("disclosures_raw", []) or disclosures

        return {
            "quote": quote,
            "news": news[:20],
            "disclosures": disclosures[:20],
        }

    # ── Agents 탭: 마지막 사이클의 에이전트별 의견 + Lessons + 최근 결정 ──
    @app.get("/api/agents")
    def api_agents() -> dict[str, Any]:
        s = get_settings()
        ticker_key = f"{s.market.value}:{s.ticker}"
        obs = store.latest_cycle_observations(ticker_key)
        lessons = store.recent_lessons(ticker_key, limit=30)
        decisions = store.recent_decisions(ticker_key, limit=20)
        audit = store.recent_audit(limit=20)
        # 에이전트별로 마지막 의견만 보여준다
        by_agent: dict[str, dict[str, Any]] = {}
        for o in obs:
            by_agent[o["agent"]] = o
        return {
            "agents": by_agent,
            "lessons": lessons,
            "recent_decisions": decisions,
            "audit": audit,
        }

    # ── 설정 조회 / 변경 ──
    @app.get("/api/settings")
    def api_settings_get() -> dict[str, Any]:
        s = get_settings()
        cfg = store.get_runtime_config()
        # 어떤 KIS 키셋이 활성인지 + 어떤 LLM 키가 채워져있는지 UI 표시용
        kis_active_filled = bool(s.active_kis_app_key and s.active_kis_app_secret)
        return {
            "env": {
                "market": s.market.value,
                "ticker": s.ticker,
                "broker": s.broker,
                "kis_env": s.kis_env,
                "kis_active_keys_filled": kis_active_filled,
                "kis_paper_keys_filled": bool(s.kis_paper_app_key and s.kis_paper_app_secret),
                "kis_live_keys_filled": bool(s.kis_app_key and s.kis_app_secret),
                "ai_provider": s.resolved_ai_provider,
                "ai_model": s.resolved_ai_model,
                "ai_keys_filled": {
                    "anthropic": bool(s.anthropic_api_key),
                    "openai": bool(s.openai_api_key),
                    "gemini": bool(s.gemini_api_key),
                },
                "cycle_hint_s": 60,
                "eval_horizon_minutes": s.eval_horizon_minutes,
            },
            "runtime": cfg,
        }

    @app.patch("/api/settings")
    def api_settings_patch(patch: SettingsPatch, request: Request) -> dict[str, Any]:
        _check_auth(request)
        changes = {k: v for k, v in patch.model_dump().items() if v is not None}
        # 유효성 검증 — 실수로 unknown 값이 들어가면 즉시 거절
        if "broker" in changes and changes["broker"] not in ("paper", "kis"):
            raise HTTPException(400, "broker must be 'paper' or 'kis'")
        if "kis_env" in changes and changes["kis_env"] not in ("paper", "live"):
            raise HTTPException(400, "kis_env must be 'paper' or 'live'")
        if "ticker_market" in changes and changes["ticker_market"] not in ("KR", "US", "HK", "CN"):
            raise HTTPException(400, "ticker_market unsupported")
        if "ai_provider" in changes and changes["ai_provider"] not in (
            "anthropic", "openai", "gemini"
        ):
            raise HTTPException(400, "ai_provider must be 'anthropic'|'openai'|'gemini'")
        if "ai_model" in changes:
            # 빈 문자열 허용 (provider 기본값 사용 의도) — 너무 긴 입력만 컷.
            if len(changes["ai_model"]) > 200:
                raise HTTPException(400, "ai_model too long")
        new_cfg = store.update_runtime_config(changes)
        store.log_audit("dashboard", "settings_patch", changes)
        return {"runtime": new_cfg}

    # ── 비상 정지 / 재개 ──
    @app.post("/api/pause")
    def api_pause(request: Request) -> dict[str, Any]:
        _check_auth(request)
        cfg = store.update_runtime_config({"paused": True})
        store.log_audit("dashboard", "pause", {})
        return {"runtime": cfg}

    @app.post("/api/resume")
    def api_resume(request: Request) -> dict[str, Any]:
        _check_auth(request)
        cfg = store.update_runtime_config({"paused": False})
        store.log_audit("dashboard", "resume", {})
        return {"runtime": cfg}

    # ── 전량 청산 ──
    @app.post("/api/flatten")
    async def api_flatten(req: FlattenRequest, request: Request) -> dict[str, Any]:
        _check_auth(request)
        if req.confirm != "FLATTEN":
            raise HTTPException(400, "missing confirm token 'FLATTEN'")
        # 실제 청산은 루프 프로세스의 포트폴리오·브로커와 닿아야 한다.
        # 대시보드가 별 프로세스라면 직접 호출이 어려우므로, 일단 '요청'만 기록.
        # 루프가 다음 사이클에 flatten_request audit 을 보고 실행하도록 한다.
        store.log_audit("dashboard", "flatten_request", {})
        return {"status": "requested"}

    # ── 재기동 ──
    @app.post("/api/restart")
    async def api_restart(req: RestartRequest, request: Request) -> dict[str, Any]:
        _check_auth(request)
        if req.confirm != "RESTART":
            raise HTTPException(400, "missing confirm token 'RESTART'")
        store.log_audit("dashboard", "restart_request", {})
        # sudoers NOPASSWD 설정되어 있으면 실제 재기동. 실패해도 500으로 보내지 말고 메시지 리턴.
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-n", "systemctl", "restart", "mimmy", "mimmy-dashboard",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            ok = proc.returncode == 0
        except FileNotFoundError:
            return {"status": "unavailable", "reason": "systemctl not found (local dev)"}
        if ok:
            store.clear_needs_restart()
            return {"status": "ok"}
        return {"status": "failed", "reason": out.decode(errors="ignore")[-400:]}

    # ── 챗 (자연어 → self-edit pipeline) ──
    @app.post("/chat", response_model=ChatResponse)
    async def chat(msg: ChatMessage, request: Request) -> ChatResponse:
        s = get_settings()
        if s.authorized_ids and int(msg.user_id) not in s.authorized_ids:
            raise HTTPException(403, "unauthorized")
        from mimmy.self_edit.pipeline import propose_change

        result = await propose_change(msg.text, requested_by=msg.user_id)
        return ChatResponse(reply=result.summary_for_user(), artifact_url=result.pr_url)

    # ── 정적 파일 + SPA 라우팅 ──
    if _STATIC_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(_STATIC_DIR), html=False),
            name="static",
        )

        @app.get("/")
        def root() -> FileResponse:
            return FileResponse(_STATIC_DIR / "index.html")

        @app.get("/manifest.webmanifest")
        def manifest() -> FileResponse:
            return FileResponse(
                _STATIC_DIR / "manifest.webmanifest",
                media_type="application/manifest+json",
            )

        @app.get("/sw.js")
        def service_worker() -> FileResponse:
            return FileResponse(_STATIC_DIR / "sw.js", media_type="application/javascript")
    else:
        @app.get("/")
        def root() -> JSONResponse:
            return JSONResponse({"error": "static dir missing"})

    return app


def run_dashboard() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "mimmy.dashboard.app:create_app",
        factory=True,
        host=s.dashboard_host,
        port=s.dashboard_port,
        log_level=s.log_level.lower(),
    )
