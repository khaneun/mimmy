from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mimmy.core.types import MarketCode

AIProvider = Literal["anthropic", "openai", "gemini"]

# provider별 기본 모델 — AI_MODEL 비워두면 이 값을 쓴다.
_DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-4o",
    "gemini": "gemini-1.5-pro",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # runtime
    env: str = Field("dev", alias="MIMMY_ENV")
    log_level: str = Field("INFO", alias="MIMMY_LOG_LEVEL")
    data_dir: Path = Field(Path("./data"), alias="MIMMY_DATA_DIR")
    db_url: str = Field("sqlite:///./data/mimmy.sqlite", alias="MIMMY_DB_URL")

    # target
    market: MarketCode = Field(MarketCode.KR, alias="MIMMY_MARKET")
    ticker: str = Field("005930", alias="MIMMY_TICKER")

    # secrets
    use_secrets_manager: bool = Field(False, alias="MIMMY_USE_SECRETS_MANAGER")
    secrets_id: str = Field("mimmy/dev", alias="MIMMY_SECRETS_ID")
    aws_region: str = Field("ap-northeast-2", alias="AWS_REGION")

    # ─── LLM (multi-provider) ───
    # 사용할 provider: anthropic | openai | gemini
    ai_provider: str = Field("anthropic", alias="AI_PROVIDER")
    # 모델명 — 비워두면 provider별 기본값을 사용한다 (resolved_ai_model 참고).
    ai_model: str = Field("", alias="AI_MODEL")
    # API 키 — 사용하는 provider 키만 채우면 된다.
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
    # 구버전 호환: MIMMY_AGENT_MODEL 가 세팅되어 있으면 ai_model로 폴백.
    legacy_agent_model: str = Field("", alias="MIMMY_AGENT_MODEL")

    # telegram
    telegram_bot_token: str = Field("", alias="TELEGRAM_BOT_TOKEN")
    authorized_telegram_ids: str = Field("", alias="AUTHORIZED_TELEGRAM_IDS")

    # dashboard
    dashboard_host: str = Field("0.0.0.0", alias="DASHBOARD_HOST")
    dashboard_port: int = Field(8787, alias="DASHBOARD_PORT")

    # self-edit
    self_edit_auto_merge: bool = Field(False, alias="SELF_EDIT_AUTO_MERGE")
    git_remote: str = Field("origin", alias="GIT_REMOTE")
    git_base_branch: str = Field("main", alias="GIT_BASE_BRANCH")

    # data sources
    dart_api_key: str = Field("", alias="DART_API_KEY")
    http_user_agent: str = Field(
        "Mozilla/5.0 (compatible; Mimmy/0.0.1)",
        alias="MIMMY_HTTP_USER_AGENT",
    )

    # broker 선택 (paper | kis)
    broker: str = Field("paper", alias="MIMMY_BROKER")

    # ─── KIS (한국투자증권) OpenAPI ───
    # 환경 선택: paper(모의투자/VTS) | live(실계좌)
    kis_env: str = Field("paper", alias="KIS_ENV")

    # 실계좌 자격증명
    kis_app_key: str = Field("", alias="KIS_APP_KEY")
    kis_app_secret: str = Field("", alias="KIS_APP_SECRET")
    # 계좌번호 — "12345678-01" 형식 또는 10자리 연속(앞 8 + 뒤 2)을 모두 허용.
    # 구버전 KIS_ACCOUNT_NO 와 신버전 KIS_ACCOUNT_NUMBER 둘 다 받는다.
    kis_account_no: str = Field(
        "",
        validation_alias=AliasChoices("KIS_ACCOUNT_NUMBER", "KIS_ACCOUNT_NO"),
    )

    # 모의투자(VTS) 자격증명 — apiportal.koreainvestment.com 모의투자 앱 별도 등록.
    kis_paper_app_key: str = Field("", alias="KIS_PAPER_APP_KEY")
    kis_paper_app_secret: str = Field("", alias="KIS_PAPER_APP_SECRET")
    kis_paper_account_no: str = Field(
        "",
        validation_alias=AliasChoices("KIS_PAPER_ACCOUNT_NUMBER", "KIS_PAPER_ACCOUNT_NO"),
    )

    # KIS 레이트리밋 / 체결폴링 — 연속 주문 에러 방지
    kis_min_gap_seconds: float = Field(0.05, alias="KIS_MIN_GAP_SECONDS")
    kis_order_min_gap_seconds: float = Field(0.5, alias="KIS_ORDER_MIN_GAP_SECONDS")
    kis_poll_interval_seconds: float = Field(1.0, alias="KIS_POLL_INTERVAL_SECONDS")
    kis_poll_timeout_seconds: float = Field(60.0, alias="KIS_POLL_TIMEOUT_SECONDS")

    # US broker — 추후
    alpaca_key_id: str = Field("", alias="ALPACA_KEY_ID")
    alpaca_secret_key: str = Field("", alias="ALPACA_SECRET_KEY")

    # 평가 루프
    eval_horizon_minutes: int = Field(30, alias="EVAL_HORIZON_MINUTES")
    eval_lessons_recent: int = Field(20, alias="EVAL_LESSONS_RECENT")
    starting_cash: float = Field(10_000_000.0, alias="MIMMY_STARTING_CASH")

    # ─── 유도 속성 ───

    @property
    def authorized_ids(self) -> set[int]:
        raw = (self.authorized_telegram_ids or "").strip()
        if not raw:
            return set()
        return {int(x) for x in raw.split(",") if x.strip()}

    @property
    def resolved_ai_provider(self) -> str:
        p = (self.ai_provider or "").strip().lower()
        return p if p in _DEFAULT_MODEL_BY_PROVIDER else "anthropic"

    @property
    def resolved_ai_model(self) -> str:
        """AI_MODEL → MIMMY_AGENT_MODEL(legacy) → provider 기본값 순으로 결정."""
        if self.ai_model.strip():
            return self.ai_model.strip()
        if self.legacy_agent_model.strip():
            return self.legacy_agent_model.strip()
        return _DEFAULT_MODEL_BY_PROVIDER[self.resolved_ai_provider]

    @property
    def resolved_ai_api_key(self) -> str:
        p = self.resolved_ai_provider
        if p == "anthropic":
            return self.anthropic_api_key
        if p == "openai":
            return self.openai_api_key
        if p == "gemini":
            return self.gemini_api_key
        return ""

    # ─── KIS 환경별 키 선택 ───

    @property
    def active_kis_app_key(self) -> str:
        return self.kis_paper_app_key if self.kis_env == "paper" else self.kis_app_key

    @property
    def active_kis_app_secret(self) -> str:
        return self.kis_paper_app_secret if self.kis_env == "paper" else self.kis_app_secret

    @property
    def active_kis_account_no(self) -> str:
        """선택된 KIS 환경의 계좌번호를 'CANO-PRDT' 형식으로 정규화해 반환."""
        raw = self.kis_paper_account_no if self.kis_env == "paper" else self.kis_account_no
        return _normalize_account_no(raw)


def _normalize_account_no(raw: str) -> str:
    """'12345678-01' 또는 '1234567801' 모두 허용. 빈값은 그대로 빈문자열."""
    s = (raw or "").strip()
    if not s:
        return ""
    if "-" in s:
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    # CANO 8자리 + PRDT 2자리 = 10자리가 표준. 그 외 길이는 호출부 검증에 맡긴다.
    if len(digits) == 10:
        return f"{digits[:8]}-{digits[8:]}"
    return s


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
