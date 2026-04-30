"""한국투자증권(KIS) OpenAPI 브로커.

- 문서: https://apiportal.koreainvestment.com
- 기본 모드는 **모의투자(VTS)**. `KIS_ENV=live` 일 때만 실계좌.
- 토큰은 24h 유효 → 프로세스 메모리에 캐시 (+ 만료 10분 전 갱신).
- 공개 엔드포인트(Naver) 대비 KIS는 호가·체결가까지 정식으로 받을 수 있지만,
  현재 스캐폴드는 시세조회와 현금 매수/매도만 구현한다.
  옵션·선물은 별도 엔드포인트로 별도 구현 예정.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from mimmy.config import get_settings
from mimmy.core.types import Action, Decision, Instrument, InstrumentKind
from mimmy.data.http import AsyncRateLimiter, fetch_with_retry
from mimmy.logging import get_logger
from mimmy.trading.broker import Broker, Fill

log = get_logger(__name__)

Env = Literal["paper", "live"]

# ─── 환경별 베이스 URL + tr_id 매핑 ───

_BASE_URLS: dict[Env, str] = {
    "paper": "https://openapivts.koreainvestment.com:29443",
    "live": "https://openapi.koreainvestment.com:9443",
}

_TR_IDS: dict[tuple[Env, str], str] = {
    # (env, op) → tr_id
    ("live", "buy"): "TTTC0802U",
    ("live", "sell"): "TTTC0801U",
    ("paper", "buy"): "VTTC0802U",
    ("paper", "sell"): "VTTC0801U",
    ("live", "cancel"): "TTTC0803U",
    ("paper", "cancel"): "VTTC0803U",
    # 체결내역 (주문체결일별 조회)
    ("live", "ccld"): "TTTC8001R",
    ("paper", "ccld"): "VTTC8001R",
    # 시세는 공용
    ("live", "price"): "FHKST01010100",
    ("paper", "price"): "FHKST01010100",
}


# KIS가 초당 건수 초과 시 내려주는 시그널들.
# - rt_cd=1 + msg_cd=EGW00121 조합이 대표적 ("초당 거래건수를 초과하였습니다")
# - 문구 변형을 위해 '초당' 키워드도 같이 본다.
_RATE_LIMIT_MSG_CODES = {"EGW00121"}
_RATE_LIMIT_MSG_HINTS = ("초당", "거래건수")


def tr_id(env: Env, op: str) -> str:
    return _TR_IDS[(env, op)]


# ─── 토큰 관리 ───


@dataclass
class _Token:
    access_token: str
    expires_at: float  # epoch seconds

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 600  # 10분 여유


class KISClient:
    """KIS HTTP 클라이언트. 인증 + 호출 + 토큰 캐시."""

    def __init__(
        self,
        *,
        env: Env,
        app_key: str,
        app_secret: str,
        account_no: str,
        global_min_gap: float | None = None,
        order_min_gap: float | None = None,
        poll_interval: float | None = None,
        poll_timeout: float | None = None,
    ) -> None:
        if env not in _BASE_URLS:
            raise ValueError(f"unknown KIS env: {env}")
        if not (app_key and app_secret and account_no):
            raise ValueError("KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO 필수")
        if "-" not in account_no:
            raise ValueError("KIS_ACCOUNT_NO 형식: '12345678-01'")

        self.env: Env = env
        self.base_url = _BASE_URLS[env]
        self.app_key = app_key
        self.app_secret = app_secret
        self.cano, self.acnt_prdt_cd = account_no.split("-", 1)

        self._token: _Token | None = None
        self._token_lock = asyncio.Lock()

        # Rate limiting — 호출 전에 반드시 통과시킨다.
        # global: 전 호출 공통. order: 주문 계열에 추가로 적용 (더 길게 잡는다).
        s = get_settings()
        self._gate = AsyncRateLimiter(
            global_min_gap if global_min_gap is not None else s.kis_min_gap_seconds
        )
        self._order_gate = AsyncRateLimiter(
            order_min_gap if order_min_gap is not None else s.kis_order_min_gap_seconds
        )
        self._poll_interval = (
            poll_interval if poll_interval is not None else s.kis_poll_interval_seconds
        )
        self._poll_timeout = (
            poll_timeout if poll_timeout is not None else s.kis_poll_timeout_seconds
        )

    async def _ensure_token(self) -> str:
        async with self._token_lock:
            if self._token is None or self._token.expired:
                self._token = await self._fetch_token()
            return self._token.access_token

    async def _fetch_token(self) -> _Token:
        resp = await fetch_with_retry(
            f"{self.base_url}/oauth2/tokenP",
            method="POST",
            headers={"Content-Type": "application/json"},
            content=__import__("json").dumps(
                {
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret,
                }
            ).encode(),
        )
        resp.raise_for_status()
        data = resp.json()
        expires_in = int(data.get("expires_in", 86400))
        log.info("kis_token_issued", env=self.env, expires_in=expires_in)
        return _Token(
            access_token=data["access_token"],
            expires_at=time.time() + expires_in,
        )

    @staticmethod
    def _is_rate_limited(data: dict[str, Any]) -> bool:
        if data.get("rt_cd") in (None, "0"):
            return False
        if str(data.get("msg_cd") or "").strip() in _RATE_LIMIT_MSG_CODES:
            return True
        msg = str(data.get("msg1") or "")
        return any(hint in msg for hint in _RATE_LIMIT_MSG_HINTS)

    async def _call(
        self,
        *,
        method: str,
        path: str,
        tr_id: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        extra_gate: AsyncRateLimiter | None = None,
    ) -> dict[str, Any]:
        token = await self._ensure_token()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
            "Content-Type": "application/json; charset=utf-8",
        }
        content = None
        if body is not None:
            import json as _json

            content = _json.dumps(body).encode()

        # rate-limit 에러는 최대 3회까지 백오프 재시도.
        # 매 시도마다 게이트를 acquire 하므로 자연스럽게 간격이 벌어진다.
        last_data: dict[str, Any] | None = None
        for attempt in range(3):
            if extra_gate is not None:
                await extra_gate.acquire()
            await self._gate.acquire()

            resp = await fetch_with_retry(
                f"{self.base_url}{path}",
                method=method,
                headers=headers,
                params=params,
                content=content,
            )
            data = resp.json()
            last_data = data

            if not self._is_rate_limited(data):
                if data.get("rt_cd") not in (None, "0"):
                    log.warning(
                        "kis_call_not_ok",
                        path=path,
                        tr_id=tr_id,
                        rt_cd=data.get("rt_cd"),
                        msg=data.get("msg1"),
                    )
                return data

            # rate-limit 신호 → 지수 백오프 후 재시도
            backoff = 0.25 * (2 ** attempt)
            log.warning(
                "kis_rate_limited",
                path=path,
                tr_id=tr_id,
                msg=data.get("msg1"),
                attempt=attempt + 1,
                backoff_s=backoff,
            )
            await asyncio.sleep(backoff)

        # 전부 rate-limit으로 실패한 경우: 마지막 응답을 그대로 반환 (호출부가 rt_cd로 판단)
        return last_data or {}

    # ─── 시세 ───

    async def inquire_price(self, symbol: str) -> dict[str, Any]:
        return await self._call(
            method="GET",
            path="/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id=tr_id(self.env, "price"),
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
            },
        )

    # ─── 주문 ───

    async def order_cash(
        self,
        *,
        side: Literal["buy", "sell"],
        symbol: str,
        quantity: int,
        price: float | None,
    ) -> dict[str, Any]:
        ord_dvsn = "01" if price is None else "00"   # 01=시장가, 00=지정가
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0" if price is None else str(int(price)),
        }
        return await self._call(
            method="POST",
            path="/uapi/domestic-stock/v1/trading/order-cash",
            tr_id=tr_id(self.env, side),
            body=body,
            extra_gate=self._order_gate,
        )

    async def cancel_order(
        self,
        *,
        krx_fwdg_ord_orgno: str,
        orgn_odno: str,
        quantity: int,
    ) -> dict[str, Any]:
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
            "ORGN_ODNO": orgn_odno,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        return await self._call(
            method="POST",
            path="/uapi/domestic-stock/v1/trading/order-rvsecncl",
            tr_id=tr_id(self.env, "cancel"),
            body=body,
            extra_gate=self._order_gate,
        )

    # ─── 체결조회 ───

    async def inquire_daily_ccld(
        self,
        *,
        odno: str | None = None,
        pdno: str | None = None,
        date_yyyymmdd: str | None = None,
    ) -> dict[str, Any]:
        """주식일별주문체결조회 (inquire-daily-ccld).

        - `odno` 로 필터링하는 게 가장 정확. 비워두면 당일 전체.
        - `date_yyyymmdd` 미지정 시 오늘 날짜로 조회.
        """
        if date_yyyymmdd is None:
            date_yyyymmdd = datetime.utcnow().strftime("%Y%m%d")
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "INQR_STRT_DT": date_yyyymmdd,
            "INQR_END_DT": date_yyyymmdd,
            "SLL_BUY_DVSN_CD": "00",  # 00=전체
            "INQR_DVSN": "00",
            "PDNO": pdno or "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": odno or "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        return await self._call(
            method="GET",
            path="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            tr_id=tr_id(self.env, "ccld"),
            params=params,
        )

    async def poll_fill(
        self,
        *,
        odno: str,
        pdno: str,
        total_qty: int,
        interval_s: float | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """체결 완료까지 inquire-daily-ccld 를 폴링한다.

        반환: {"filled_qty": int, "avg_price": float, "remaining_qty": int, "cancelled_qty": int, "done": bool}
        - `done` 은 (filled + cancelled) >= total_qty 또는 timeout.
        - timeout 이 나면 done=False. 호출부가 판단하도록 한다.
        """
        interval = interval_s if interval_s is not None else self._poll_interval
        timeout = timeout_s if timeout_s is not None else self._poll_timeout
        deadline = time.monotonic() + timeout

        last: dict[str, Any] = {
            "filled_qty": 0,
            "avg_price": 0.0,
            "remaining_qty": total_qty,
            "cancelled_qty": 0,
            "done": False,
        }

        while True:
            payload = await self.inquire_daily_ccld(odno=odno, pdno=pdno)
            parsed = parse_ccld_for_odno(payload, odno=odno)
            last = {**parsed, "done": False}
            filled = parsed["filled_qty"]
            cancelled = parsed["cancelled_qty"]
            if filled + cancelled >= total_qty and total_qty > 0:
                last["done"] = True
                return last
            if time.monotonic() >= deadline:
                log.warning(
                    "kis_poll_fill_timeout",
                    odno=odno,
                    pdno=pdno,
                    filled=filled,
                    total=total_qty,
                )
                return last
            await asyncio.sleep(interval)


# ─── Broker 구현 ───


_SUPPORTED_KINDS = {InstrumentKind.COMMON, InstrumentKind.PREFERRED}


def _parse_price(output: dict[str, Any]) -> float | None:
    """inquire_price 응답의 output에서 현재가(stck_prpr) 추출."""
    if not output:
        return None
    v = output.get("stck_prpr") or output.get("STCK_PRPR")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(v: Any) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0.0)
    except (TypeError, ValueError):
        return 0.0


def parse_ccld_for_odno(
    payload: dict[str, Any], *, odno: str | None
) -> dict[str, Any]:
    """inquire-daily-ccld 응답에서 특정 주문번호의 체결 상태를 뽑는다.

    반환: {"filled_qty", "avg_price", "remaining_qty", "cancelled_qty"}
    - output1(주문 단위 리스트)을 순회.
    - odno 지정 시 그 주문번호만, 아니면 전체 합산.
    """
    rows = payload.get("output1") or payload.get("OUTPUT1") or []
    filled_qty = 0
    remaining_qty = 0
    cancelled_qty = 0
    # 평균단가는 체결수량 가중평균으로 재계산 (응답의 avg_prvs는 여러 주문을 섞을 수 있음).
    weighted_sum = 0.0

    for row in rows:
        row_odno = str(row.get("odno") or row.get("ODNO") or "").strip()
        if odno and row_odno != odno:
            continue
        q = _to_int(row.get("tot_ccld_qty") or row.get("TOT_CCLD_QTY"))
        filled_qty += q
        remaining_qty += _to_int(row.get("rmn_qty") or row.get("RMN_QTY"))
        cancelled_qty += _to_int(row.get("cncld_qty") or row.get("CNCLD_QTY"))
        # avg_prvs(평균체결가)가 있으면 그걸, 없으면 avg_ord_unpr(평균주문단가)로 대체.
        p = _to_float(
            row.get("avg_prvs")
            or row.get("AVG_PRVS")
            or row.get("avg_ord_unpr")
            or row.get("AVG_ORD_UNPR")
        )
        if q > 0 and p > 0:
            weighted_sum += p * q

    avg_price = (weighted_sum / filled_qty) if filled_qty > 0 else 0.0
    return {
        "filled_qty": filled_qty,
        "avg_price": avg_price,
        "remaining_qty": remaining_qty,
        "cancelled_qty": cancelled_qty,
    }


class KISBroker(Broker):
    def __init__(self, client: KISClient | None = None) -> None:
        if client is None:
            s = get_settings()
            if s.kis_env not in ("paper", "live"):
                raise ValueError(f"KIS_ENV 는 paper|live — 현재값: {s.kis_env}")
            # paper/live 각각의 키셋을 분리 보관 (.env에 KIS_PAPER_*/KIS_* 둘 다 채울 수 있음).
            client = KISClient(
                env=s.kis_env,  # type: ignore[arg-type]
                app_key=s.active_kis_app_key,
                app_secret=s.active_kis_app_secret,
                account_no=s.active_kis_account_no,
            )
        self._client = client

    async def submit(self, decision: Decision) -> Fill:
        inst = decision.instrument
        if inst.kind not in _SUPPORTED_KINDS:
            raise NotImplementedError(
                f"KIS broker: {inst.kind.value} 상품은 현재 지원 안함 (주식만)"
            )
        if decision.action not in (Action.BUY, Action.SELL):
            raise ValueError(f"KIS broker cannot handle action {decision.action}")

        total_qty = int(decision.quantity)
        result = await self._client.order_cash(
            side="buy" if decision.action == Action.BUY else "sell",
            symbol=inst.symbol,
            quantity=total_qty,
            price=decision.limit_price,
        )

        # 주문 접수 단계에서 rt_cd != 0 → 체결 수량 0 Fill 리턴 (loop.py 에서 skip).
        if result.get("rt_cd") not in (None, "0"):
            log.warning(
                "kis_order_rejected",
                rt_cd=result.get("rt_cd"),
                msg=result.get("msg1"),
                instrument=inst.key,
            )
            return Fill(
                instrument=inst,
                side=decision.action,
                quantity=0.0,
                price=0.0,
                filled_at=datetime.utcnow(),
                broker_order_id="",
            )

        output = result.get("output") or {}
        odno = str(output.get("ODNO") or output.get("odno") or "").strip()

        # 주문번호가 없으면 폴링 불가 → 한도 상태로 0 Fill 리턴.
        if not odno:
            log.warning("kis_order_no_odno", result=result)
            return Fill(
                instrument=inst,
                side=decision.action,
                quantity=0.0,
                price=0.0,
                filled_at=datetime.utcnow(),
                broker_order_id="",
            )

        # 체결 폴링: 실체결 수량·평균단가 확보.
        fill_info = await self._client.poll_fill(
            odno=odno, pdno=inst.symbol, total_qty=total_qty
        )
        filled_qty = int(fill_info.get("filled_qty") or 0)
        avg_price = float(fill_info.get("avg_price") or 0.0)

        # 평균단가 fallback: 폴링에서 0이 나오면 limit_price → 직전 현재가 순으로 대체.
        if avg_price <= 0 and filled_qty > 0:
            if decision.limit_price is not None:
                avg_price = float(decision.limit_price)
            else:
                price_resp = await self._client.inquire_price(inst.symbol)
                avg_price = float(_parse_price(price_resp.get("output") or {}) or 0.0)

        return Fill(
            instrument=inst,
            side=decision.action,
            quantity=float(filled_qty),
            price=avg_price,
            filled_at=datetime.utcnow(),
            broker_order_id=odno,
        )

    async def cancel(self, broker_order_id: str) -> bool:
        # 단순화: 미구현. KRX_FWDG_ORD_ORGNO 가 필요하므로 호출부에서 전달해야 함.
        log.warning("kis_cancel_not_implemented", order_id=broker_order_id)
        return False

    # 시세 쿼리는 Broker 인터페이스 밖이지만 evaluator에서 재사용 가능
    async def fetch_price(self, instrument: Instrument) -> float | None:
        if instrument.kind not in _SUPPORTED_KINDS:
            return None
        resp = await self._client.inquire_price(instrument.symbol)
        return _parse_price(resp.get("output") or {})
