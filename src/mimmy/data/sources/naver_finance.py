"""Naver Finance 데이터 소스.

엔드포인트 (모두 공개, key 불필요. User-Agent는 일반 브라우저값 권장):
- 실시간 시세: https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:<code>
- 뉴스 피드  : https://m.stock.naver.com/api/news/stock/<code>?pageSize=20&page=1
- 일봉       : https://fchart.stock.naver.com/sise.nhn?symbol=<code>&timeframe=day&count=30&requestType=0

순수 파싱 함수(`parse_quote_json`, `parse_news_json`)는 네트워크 I/O 없이 호출 가능 —
고정 샘플로 단위 테스트한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mimmy.core.types import Instrument, Ticker
from mimmy.data.http import TTLCache, fetch_with_retry
from mimmy.data.news import NewsItem
from mimmy.data.prices import Quote
from mimmy.logging import get_logger

log = get_logger(__name__)

_QUOTE_CACHE = TTLCache(default_ttl=5.0)    # 시세는 5초 캐시
_NEWS_CACHE = TTLCache(default_ttl=60.0)    # 뉴스는 1분 캐시

_REALTIME_URL = "https://polling.finance.naver.com/api/realtime"
_NEWS_URL = "https://m.stock.naver.com/api/news/stock/{code}"


# ─── 순수 파서 ───


def parse_quote_json(payload: dict[str, Any], instrument: Instrument) -> Quote | None:
    """Naver realtime JSON → Quote.

    응답 포맷(요약):
    { "result": { "areas": [ { "datas": [ { "cd": "005930", "nv": 72500,
        "sv": 72000, "hv": 73000, "lv": 71900, "aq": 12345, ... } ] } ] } }

    - nv: 현재가, sv: 기준가(전일종가), hv: 고가, lv: 저가
    - aq: 거래량 (주식 수)
    - cd: 종목코드
    """
    result = payload.get("result") or {}
    areas = result.get("areas") or []
    for area in areas:
        for d in area.get("datas") or []:
            if str(d.get("cd")) == instrument.symbol:
                last = _to_float(d.get("nv"))
                return Quote(
                    instrument=instrument,
                    bid=None,   # 공개 엔드포인트는 호가 미제공 → 브로커 레벨에서 보강
                    ask=None,
                    last=last,
                    volume=_to_float(d.get("aq")),
                    as_of=datetime.utcnow(),
                )
    return None


def parse_news_json(payload: Any, ticker: Ticker) -> list[NewsItem]:
    """Naver mobile stock news JSON → NewsItem 리스트.

    최근 응답은 리스트 루트 ([]) 로 내려오는 경우와 `items` 키로 감싸는 경우가 혼재.
    둘 다 관용적으로 처리한다.
    """
    items_raw: list[Any]
    if isinstance(payload, list):
        items_raw = payload
    elif isinstance(payload, dict):
        items_raw = payload.get("items") or payload.get("list") or []
    else:
        return []

    out: list[NewsItem] = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        headline = it.get("title") or it.get("headline")
        if not headline:
            continue
        url = it.get("linkUrl") or it.get("link") or it.get("url") or ""
        source = it.get("officeName") or it.get("source") or "naver"
        published = _parse_dt(
            it.get("datetime") or it.get("dateTime") or it.get("publishedAt") or ""
        )
        out.append(
            NewsItem(
                ticker=ticker,
                headline=headline,
                url=url,
                source=source,
                published_at=published or datetime.utcnow(),
                body=it.get("summary") or None,
            )
        )
    return out


# ─── 네트워크 호출 ───


async def fetch_kr_quote(instrument: Instrument) -> Quote | None:
    async def _do() -> Quote | None:
        resp = await fetch_with_retry(
            _REALTIME_URL,
            params={"query": f"SERVICE_ITEM:{instrument.symbol}"},
        )
        if resp.status_code != 200:
            log.warning("naver_quote_non_200", status=resp.status_code, symbol=instrument.symbol)
            return None
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            log.warning("naver_quote_bad_json", body=resp.text[:200])
            return None
        return parse_quote_json(payload, instrument)

    return await _QUOTE_CACHE.get_or_fetch(f"quote:{instrument.key}", _do)


async def fetch_kr_news(ticker: Ticker, page_size: int = 20) -> list[NewsItem]:
    async def _do() -> list[NewsItem]:
        resp = await fetch_with_retry(
            _NEWS_URL.format(code=ticker.symbol),
            params={"pageSize": page_size, "page": 1},
        )
        if resp.status_code != 200:
            log.warning("naver_news_non_200", status=resp.status_code, symbol=ticker.symbol)
            return []
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            log.warning("naver_news_bad_json", body=resp.text[:200])
            return []
        return parse_news_json(payload, ticker)

    return await _NEWS_CACHE.get_or_fetch(f"news:{ticker.key}", _do)


# ─── 내부 헬퍼 ───


def _to_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_dt(s: str) -> datetime | None:
    """Naver는 'yyyyMMddHHmmss' 또는 'yyyy-MM-dd HH:mm:ss' 등으로 내려준다."""
    if not s:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
