# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 개발 명령어

의존성 설치 및 실행 환경은 `uv` 기반이다.

```bash
uv sync                          # 의존성 설치 (pyproject.toml 기준)
uv run mimmy run                 # 루프 + 봇 + 대시보드 통합 실행 (개발용)
uv run mimmy loop                # 거래 루프만
uv run mimmy dashboard           # 대시보드만 (포트 8787)
uv run mimmy bot                 # 텔레그램 봇만
```

테스트 / 린트:

```bash
uv run pytest -q                      # 전체 테스트
uv run pytest tests/test_kis_broker.py -q   # 파일 단위
uv run pytest -k "test_pause" -q      # 이름 패턴
uv run ruff check src tests           # 린트
uv run ruff format src tests          # 포맷
uv run python3 -m compileall -q src tests  # 빠른 구문 체크 (pytest 없이)
```

실행 전에 `.env.example`을 `.env`로 복사해 값을 채운다. `ANTHROPIC_API_KEY`·`DART_API_KEY`·KIS 자격증명 없이도 `paper` 브로커 모드로 루프는 돌아간다.

## 핵심 아키텍처

### 단일 종목 원칙

`MIMMY_MARKET` + `MIMMY_TICKER` 두 값이 전체 시스템의 거래 대상을 완전히 결정한다. 거래 가능한 Instrument 목록은 `instruments/resolver.py` → `markets/<시장>.py:resolve_instruments()` 가 유일한 진입점이다. 이 목록 밖의 종목은 절대 주문하지 않는다.

### 사이클 흐름

```
run_loop()  ←→  runtime_config(DB) → paused 체크
  │
  ├─ process_due_evaluations()          # 체결 N분 후 사후 평가
  ├─ build_context()                    # 뉴스·공시·시세 병렬 수집
  ├─ Orchestrator.cycle()               # 에이전트 팀 실행
  │    ├─ NewsAnalyst / DisclosureAnalyst / MarketAnalyst  →  Signal
  │    ├─ Trader.decide(ctx, signals)   →  Decision
  │    └─ RiskManager.evaluate(decision) →  RiskDecision
  ├─ KISBroker / PaperBroker.submit()  # 주문 → Fill (KIS는 poll_fill로 실체결 대기)
  └─ store.write_snapshot()            # 대시보드용 스냅샷
```

### 데이터 흐름

- `data/sources/naver_finance.py` — 시세·뉴스 (TTL 캐시, fetch_with_retry 경유)
- `data/sources/dart.py` — 공시 (corp_code XML ZIP을 24h 디스크 캐시)
- 모든 외부 HTTP 호출은 `data/http.py:fetch_with_retry` 를 경유 (User-Agent 통일, 3회 지수 백오프)
- KIS API 호출은 `trading/kis.py:AsyncRateLimiter` 2단 게이트 통과 후 실행 (global 50ms + order 500ms)

### 영속화 (SQLite, `runtime/store.py`)

| 테이블 | 용도 |
|---|---|
| `decisions` | 체결된 결정 + 평가 예약/결과 |
| `lessons` | Evaluator가 뽑은 교훈 → Trader 프롬프트 주입 |
| `audit_log` | self-edit·주문거부·flatten 등 운영 이벤트 |
| `runtime_snapshots` | 매 사이클 포트폴리오 스냅샷 (대시보드 홈) |
| `agent_observations` | 매 사이클 에이전트별 Signal/Decision/RiskGate (대시보드 Agents 탭) |
| `runtime_config` | 대시보드가 토글하는 설정 (paused·broker·kis_env 등), 단일 행 id=1 |

루프와 대시보드는 별도 프로세스로 돌 수 있다. 대시보드는 DB를 read + 플래그 write만 하고, 루프가 매 사이클 초두에 `runtime_config` 를 읽어 paused 여부·flatten 요청을 소비한다.

### LLM 에이전트 공통

`agents/base.py:Agent` 를 상속. `system_prompt` + `output_model`(Pydantic) 선언 후 `_call()` 호출.
- 시스템 프롬프트는 `cache_control: ephemeral` 로 Anthropic 프롬프트 캐시 활용
- 출력은 JSON 스키마 강제; `_extract_json()` 이 ```json 블록도 파싱

Evaluator는 체결 후 `EVAL_HORIZON_MINUTES` 경과 시 `process_due_evaluations()` 에서 호출되어 `lessons`를 `LessonRow`에 기록 → 다음 사이클 Trader 프롬프트에 자동 주입된다.

### 브로커

- `trading/broker.py:PaperBroker` — 즉시 체결 시뮬레이터 (기본값)
- `trading/kis.py:KISBroker` — KIS OpenAPI. `order_cash()` → `poll_fill()` 로 실체결 대기. 연속 주문 에러 방지를 위해 `_gate`(전 호출 공통)·`_order_gate`(주문 계열 추가) AsyncRateLimiter 통과 필수. rate-limit 응답(`EGW00121` / "초당") 감지 시 최대 3회 지수 백오프 재시도.
- `MIMMY_BROKER=paper|kis` 로 선택. KIS 실계좌는 `KIS_ENV=live` 추가 필요.

### 대시보드 (FastAPI + 모바일 SPA)

- API: `/api/home`, `/api/market`, `/api/agents`, `/api/settings`, `/api/pause`, `/api/resume`, `/api/flatten`, `/api/restart`, `/chat`
- SPA: `dashboard/static/` — 순수 JS (프레임워크 없음), 하단 탭바 5개, PWA(`manifest.webmanifest` + `sw.js`)
- 권한: `X-Mimmy-User` 헤더 → `AUTHORIZED_TELEGRAM_IDS` 검증. 비어있으면 개발모드(무인증).
- 파괴적 액션(`/api/flatten`, `/api/restart`)은 각각 확인 토큰 `"FLATTEN"` / `"RESTART"` 를 body에 포함해야 한다.

### 자기 수정 파이프라인

텔레그램 `/improve <지시>` 또는 대시보드 챗 → `self_edit/pipeline.py:propose_change()`:
1. feature 브랜치 checkout
2. `self_edit/editor.py:propose_edits()` (현재 스텁 — 실제 LLM 파일편집 루프 미구현)
3. 컴파일 + pytest smoke test
4. commit → push → PR 생성
5. `SELF_EDIT_AUTO_MERGE=true` + 테스트 통과 시에만 `gh pr merge --squash --auto` → `systemctl restart`

## 주요 확장 포인트

- **새 시장 추가**: `markets/<코드>.py` 에 `Market` 상속 구현 → `markets/registry.py` 에 등록
- **새 데이터 소스**: `data/sources/` 에 추가, `data/prices.py` / `data/news.py` / `data/disclosure.py` 의 디스패처에서 분기
- **US 브로커 (Alpaca)**: `trading/broker.py` 의 `Broker` 추상 구현, `runtime/loop.py:make_broker()` 에 분기 추가
- **self_edit/editor.py**: `propose_edits()` 스텁을 실제 Claude 파일편집 루프로 교체하는 것이 다음 큰 작업

## 주의사항

- `get_settings()` 는 `@lru_cache` 되어있다. 테스트에서 env를 바꾸면 `get_settings.cache_clear()` + `store._engine = None` 을 같이 호출해야 격리된다.
- SQLModel 테이블 클래스는 `table=True` 플래그로 구분. 모델 변경 시 마이그레이션 로직은 없으므로 개발 중 `data/mimmy.sqlite` 삭제 후 재기동하면 `create_all()` 로 재생성된다.
- `KISClient.__init__` 은 `get_settings()` 를 호출하므로 테스트에서 직접 인스턴스화할 때 `global_min_gap=0`, `order_min_gap=0` 을 전달하면 레이트리밋 없이 사용할 수 있다.
- 대시보드 포트(8787)는 외부에 열지 말 것. self_edit 챗이 붙어있어 노출 시 임의 코드 실행으로 이어질 수 있다.
