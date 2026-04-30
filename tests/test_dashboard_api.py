from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def client(monkeypatch):
    """각 테스트마다 격리된 SQLite + Settings + store 엔진을 쓴다."""
    from fastapi.testclient import TestClient

    tmpdir = tempfile.mkdtemp(prefix="mimmy-dash-")
    db_path = Path(tmpdir) / "mimmy.sqlite"
    os.environ["MIMMY_DB_URL"] = f"sqlite:///{db_path}"
    os.environ["MIMMY_DATA_DIR"] = tmpdir
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    os.environ.setdefault("MIMMY_MARKET", "KR")
    os.environ.setdefault("MIMMY_TICKER", "005930")
    os.environ.setdefault("MIMMY_BROKER", "paper")
    os.environ["AUTHORIZED_TELEGRAM_IDS"] = ""  # auth off
    # lru_cache된 get_settings 비우기 + store 엔진 리셋
    from mimmy.config import get_settings
    get_settings.cache_clear()
    from mimmy.runtime import store as store_mod
    store_mod._engine = None  # type: ignore[attr-defined]

    from mimmy.dashboard.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_home_empty(client):
    """스냅샷이 없을 때도 500 없이 응답."""
    r = client.get("/api/home")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"]["market"] == "KR"
    assert body["ticker"]["symbol"] == "005930"
    assert body["snapshot"] is None
    assert body["equity_series"] == []
    assert body["paused"] is False


def test_settings_patch_creates_restart_flag(client):
    # 초기
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["runtime"]["needs_restart"] is False

    # broker 토글 → 재기동 플래그
    r = client.patch("/api/settings", json={"broker": "kis"})
    assert r.status_code == 200
    cfg = r.json()["runtime"]
    assert cfg["broker"] == "kis"
    assert cfg["needs_restart"] is True

    # paused는 재기동 불필요
    r = client.patch("/api/settings", json={"paused": True})
    assert r.status_code == 200
    assert r.json()["runtime"]["paused"] is True


def test_settings_rejects_invalid_values(client):
    r = client.patch("/api/settings", json={"broker": "etrade"})
    assert r.status_code == 400
    r = client.patch("/api/settings", json={"kis_env": "prod"})
    assert r.status_code == 400
    r = client.patch("/api/settings", json={"ticker_market": "XX"})
    assert r.status_code == 400


def test_pause_resume_cycle(client):
    r = client.post("/api/pause")
    assert r.status_code == 200
    assert r.json()["runtime"]["paused"] is True

    r = client.post("/api/resume")
    assert r.status_code == 200
    assert r.json()["runtime"]["paused"] is False


def test_flatten_requires_confirm_token(client):
    r = client.post("/api/flatten", json={"confirm": "no"})
    assert r.status_code == 400
    r = client.post("/api/flatten", json={"confirm": "FLATTEN"})
    assert r.status_code == 200
    assert r.json()["status"] == "requested"


def test_restart_requires_confirm_token(client):
    r = client.post("/api/restart", json={"confirm": "oops"})
    assert r.status_code == 400
    # 실제 systemctl 호출은 TestClient 안에서 실행될 수 있다 — 결과와 무관하게 2xx여야 한다.
    r = client.post("/api/restart", json={"confirm": "RESTART"})
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "failed", "unavailable")


def test_agents_empty(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert body["agents"] == {}
    assert body["lessons"] == []
    assert body["recent_decisions"] == []


def test_market_empty(client):
    r = client.get("/api/market")
    assert r.status_code == 200
    body = r.json()
    assert body["quote"] is None
    assert body["news"] == []
    assert body["disclosures"] == []


def test_home_reflects_snapshot(client):
    """write_snapshot 후 /api/home 이 그 값을 반환해야 한다."""
    from mimmy.runtime import store
    store.write_snapshot(
        ticker_key="KR:005930",
        trading_state="watching",
        available_cash=10_000_000,
        equity=10_050_000,
        unrealized_pnl=50_000,
        realized_pnl=0,
        daily_pnl=50_000,
        paused=False,
        positions=[],
        last_quote={"last": 72_000, "as_of": "2026-04-21T00:00:00"},
    )
    r = client.get("/api/home")
    assert r.status_code == 200
    snap = r.json()["snapshot"]
    assert snap["equity"] == 10_050_000
    assert snap["daily_pnl"] == 50_000
    assert snap["last_quote"]["last"] == 72_000


def test_auth_enforced_when_ids_configured(client, monkeypatch):
    """AUTHORIZED_TELEGRAM_IDS 가 세팅되면 변경 API는 헤더를 요구한다."""
    os.environ["AUTHORIZED_TELEGRAM_IDS"] = "12345"
    from mimmy.config import get_settings
    get_settings.cache_clear()
    r = client.post("/api/pause")  # no X-Mimmy-User
    assert r.status_code == 401
    r = client.post("/api/pause", headers={"X-Mimmy-User": "99999"})
    assert r.status_code == 403
    r = client.post("/api/pause", headers={"X-Mimmy-User": "12345"})
    assert r.status_code == 200


def test_observation_round_trip(client):
    """write_observation 직후 latest_cycle_observations 로 조회되어야 한다."""
    from mimmy.runtime import store
    store.write_observation(
        ticker_key="KR:005930",
        cycle_id="c1",
        agent="news",
        kind="signal",
        summary="호재 우세",
        payload={"score": 0.4, "confidence": 0.6, "news_raw": [
            {"headline": "삼성전자 어닝 서프라이즈", "url": "http://x", "source": "yna",
             "published_at": "2026-04-21T00:00:00"}
        ]},
    )
    r = client.get("/api/agents")
    agents = r.json()["agents"]
    assert "news" in agents
    assert agents["news"]["summary"] == "호재 우세"

    r = client.get("/api/market")
    news = r.json()["news"]
    assert len(news) == 1
    assert news[0]["headline"].startswith("삼성전자")
