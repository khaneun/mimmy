from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MarketCode(str, Enum):
    KR = "KR"
    US = "US"
    HK = "HK"
    CN = "CN"


class InstrumentKind(str, Enum):
    COMMON = "common"       # 보통주
    PREFERRED = "preferred"  # 우선주
    CALL = "call"           # 콜옵션
    PUT = "put"             # 풋옵션
    FUTURE = "future"       # 선물
    ETF = "etf"             # 관련 ETF


class Ticker(BaseModel):
    """사용자가 고르는 '대상'. 이 티커에 묶인 모든 Instrument를 Mimmy가 거래한다."""

    market: MarketCode
    symbol: str = Field(..., description="시장별 표준 심볼 — KR: 종목코드, US: 티커")
    name: str | None = None

    @property
    def key(self) -> str:
        return f"{self.market.value}:{self.symbol}"


class Instrument(BaseModel):
    """실제 주문 단위. Ticker 하나에 여러 Instrument가 연결된다."""

    ticker: Ticker
    kind: InstrumentKind
    symbol: str  # 이 상품 자체의 식별자 (예: 옵션코드, 선물코드)
    strike: float | None = None     # 옵션 행사가
    expiry: datetime | None = None  # 옵션/선물 만기
    multiplier: float = 1.0

    @property
    def key(self) -> str:
        return f"{self.ticker.key}|{self.kind.value}:{self.symbol}"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Signal(BaseModel):
    """Analyst 에이전트들이 방출하는 관찰. Trader가 이를 종합한다."""

    source: str          # 에이전트 이름
    ticker: Ticker
    score: float         # -1.0 (강한 매도) ~ +1.0 (강한 매수)
    confidence: float    # 0 ~ 1
    rationale: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Decision(BaseModel):
    """Trader + Risk가 거친 최종 주문 결정."""

    instrument: Instrument
    action: Action
    quantity: float
    limit_price: float | None = None
    rationale: str
    signals: list[Signal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PositionState(str, Enum):
    FLAT = "flat"        # 관망
    LONG = "long"        # 보통주/콜 매수 상태
    SHORT = "short"      # 풋/인버스/선물매도
    HEDGED = "hedged"    # 양방향으로 묶여 있는 상태


class Position(BaseModel):
    instrument: Instrument
    quantity: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


OrderSide = Literal["buy", "sell"]
OrderKind = Literal["market", "limit"]
