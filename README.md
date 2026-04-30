# Mimmy

단일 종목 집중 거래 시스템.
하나의 티커가 주어지면, 그 티커와 관련된 모든 금융상품(보통주·우선주·옵션·선물)을 묶어
LLM Agent 팀이 `buy / sell / hold / hedge` 판단을 반복하며 수익을 낸다.

> Mimmy는 산리오 캐릭터(헬로키티의 동생)에서 따온 코드네임이다. 의미는 없다.

## 핵심 컨셉

- **단일 종목 원칙** — 예: 삼성전자면 보통주/우선주/콜·풋 옵션/선물 모두 거래, 그 외 종목은 건드리지 않는다.
- **상태 전환으로 수익 창출** — 관망 / 롱 / 숏 / 헷지 네 상태 사이를 움직이며 변동마다 이익을 뽑는다.
- **에이전트 팀** — 뉴스·공시·시세·호가를 각각 읽는 analyst들이 `Trader` 에이전트에게 근거를 넘기고,
  `Risk` 에이전트가 포지션 한도를 검증한 뒤 실제 발주. 사후엔 `Evaluator` 에이전트가 결과를 채점해 프롬프트·규칙을 개선한다.
- **멀티마켓** — 한국(KR) / 미국(US) / 홍콩(HK) / 중국(CN) 각각 어댑터.
- **텔레그램 제일주의** — 현황 조회부터 로직 수정·배포까지 텔레그램 한 채널에서.

## 아키텍처

```
        ┌────────────── Telegram Bot ──────────────┐
        │   (명령어 + 자연어 → self_edit pipeline) │
        └────────────┬────────────────┬────────────┘
                     │                │
              ┌──────▼─────┐   ┌──────▼──────┐
              │ Dashboard  │   │  Orchestr.  │
              │ (FastAPI)  │   │  (loop)     │
              └──────┬─────┘   └──────┬──────┘
                     │                │
                     │        ┌───────┴────────┐
                     │        │   Agents       │
                     │        │ news/mkt/disc  │
                     │        │   → trader     │
                     │        │   → risk       │
                     │        │   → evaluator  │
                     │        └───────┬────────┘
                     │                │
                     │        ┌───────▼────────┐
                     │        │  Trading/Brokr │
                     │        └───────┬────────┘
                     │                │
                ┌────▼────────────────▼────┐
                │  Markets (KR/US/HK/CN)   │
                │   + Data providers       │
                └──────────────────────────┘
```

## 레이아웃

```
src/mimmy/
  core/          도메인 타입
  config.py      pydantic-settings 기반 설정
  secrets.py     AWS Secrets Manager
  markets/       시장 어댑터 (추상 + KR/US/HK/CN 스텁)
  instruments/   티커 → 관련 상품 해석기
  data/          뉴스/공시/가격 수집
  agents/        LLM 에이전트 팀
  trading/       Broker/Portfolio/Strategy
  telegram_bot/  텔레그램 명령 + 자연어 라우터
  dashboard/     FastAPI 대시보드
  self_edit/     자연어 → 코드 수정 → git push → systemd restart
  runtime/       메인 루프, 영속화
  main.py        엔트리포인트
```

## 빠른 시작 (로컬)

```bash
make install
cp .env.example .env   # 값 채우기 (개발용)
make run               # 오케스트레이터 + 텔레그램 봇 + 대시보드
```

## 배포 (EC2)

```bash
bash deploy/ec2-setup.sh
sudo systemctl enable --now mimmy mimmy-dashboard
```

운영 시엔 `.env` 값 대신 AWS Secrets Manager의 `mimmy/<env>` 시크릿을 사용한다 (`MIMMY_USE_SECRETS_MANAGER=true`).

## 자기 수정 파이프라인 안전장치

텔레그램/대시보드 챗에서 "계산 로직 바꿔줘" 식의 자연어가 들어오면:

1. 발신자 ID가 `AUTHORIZED_TELEGRAM_IDS` 에 속하는지 확인
2. LLM이 diff를 제안
3. `self_edit/pipeline.py` 가 feature 브랜치 체크아웃 → 적용 → 최소 smoke test → commit → push
4. 기본값은 **PR 생성까지만**. `auto-merge` 플래그가 true여야 main에 머지 후 systemd restart
5. 모든 단계는 `audit_log` 테이블에 기록

무인 자동 머지 + 재기동은 기본 비활성. `/confirm` 명령으로만 켜진다.

## 현재 상태

대부분의 모듈은 인터페이스와 스텁만 정의되어 있다.
다음 반복에서 우선순위대로 실체를 채운다:

1. KR 마켓 (DART 공시 + 네이버 금융 시세 + 키움 OpenAPI 브로커)
2. Agent 프롬프트 & Claude API 연동
3. Evaluator 피드백 루프
4. US 마켓 (EDGAR + polygon.io + Alpaca)
5. HK / CN
