"""DART 공시 소스 — opendart.fss.or.kr.

흐름:
1) corp_code 매핑: https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=<KEY>
   → ZIP → CORPCODE.xml 한 개
   → 전 종목에 대해 <list><corp_code/><corp_name/><stock_code/></list> 반복
   로컬 디스크에 캐시 (24h), 메모리에도 dict로 로드.
2) 공시 리스트: https://opendart.fss.or.kr/api/list.json
   파라미터: crtfc_key, corp_code, bgn_de (yyyymmdd), page_count (기본 10)

주요 공시 카테고리(rm, report_nm 기반으로 간략히 분류):
- material-event: 주요사항보고서, 증자/감자, 자사주, 대량보유 변동, 경영권 분쟁 등
- periodic     : 분기/반기/사업보고서
- other        : 그 외
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from mimmy.config import get_settings
from mimmy.core.types import Ticker
from mimmy.data.disclosure import Disclosure
from mimmy.data.http import TTLCache, fetch_with_retry
from mimmy.logging import get_logger

log = get_logger(__name__)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

_DISCLOSURE_CACHE = TTLCache(default_ttl=120.0)  # 2분 캐시

# stock_code → corp_code 매핑. 최초 로드 후 프로세스 수명 동안 유지.
_CORP_MAP: dict[str, str] | None = None


# ─── 카테고리 분류 ───

_MATERIAL_PATTERNS = (
    "주요사항보고서",
    "유상증자", "무상증자", "감자",
    "자기주식", "자사주",
    "주식등의대량보유", "임원ㆍ주요주주",
    "합병", "분할", "영업양수도",
    "최대주주변경", "경영권",
    "회사채", "전환사채", "신주인수권부사채",
)
_PERIODIC_PATTERNS = ("분기보고서", "반기보고서", "사업보고서")


def _classify(report_nm: str) -> str:
    if any(p in report_nm for p in _MATERIAL_PATTERNS):
        return "material-event"
    if any(p in report_nm for p in _PERIODIC_PATTERNS):
        return "periodic"
    return "other"


# ─── 순수 파서 ───


def parse_corp_code_xml(xml_bytes: bytes) -> dict[str, str]:
    """CORPCODE.xml → {stock_code: corp_code}. 상장사(stock_code 있는 것)만."""
    out: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code and stock_code != " " and corp_code:
            out[stock_code] = corp_code
    return out


def parse_list_json(payload: dict[str, Any], ticker: Ticker) -> list[Disclosure]:
    """DART list.json → Disclosure 리스트."""
    if payload.get("status") and payload["status"] != "000":
        log.warning("dart_status_not_000", status=payload.get("status"), msg=payload.get("message"))
        return []
    items = payload.get("list") or []
    out: list[Disclosure] = []
    for it in items:
        report_nm = it.get("report_nm", "")
        rcept_no = it.get("rcept_no", "")
        rcept_dt = it.get("rcept_dt", "")
        try:
            filed_at = datetime.strptime(rcept_dt, "%Y%m%d")
        except ValueError:
            continue
        out.append(
            Disclosure(
                ticker=ticker,
                title=report_nm.strip(),
                url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                filed_at=filed_at,
                category=_classify(report_nm),
            )
        )
    return out


# ─── 네트워크 호출 ───


async def load_corp_map() -> dict[str, str]:
    """corp_code 매핑을 메모리 + 디스크 캐시 경유로 로드."""
    global _CORP_MAP
    if _CORP_MAP is not None:
        return _CORP_MAP

    settings = get_settings()
    if not settings.dart_api_key:
        log.warning("dart_api_key_missing — corp_map empty")
        _CORP_MAP = {}
        return _CORP_MAP

    cache_path = settings.data_dir / "cache" / "corp_code.xml"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    xml_bytes: bytes | None = None
    if cache_path.exists():
        age = datetime.utcnow() - datetime.utcfromtimestamp(cache_path.stat().st_mtime)
        if age < timedelta(hours=24):
            xml_bytes = cache_path.read_bytes()

    if xml_bytes is None:
        resp = await fetch_with_retry(
            _CORP_CODE_URL, params={"crtfc_key": settings.dart_api_key}
        )
        if resp.status_code != 200:
            log.warning("dart_corp_code_non_200", status=resp.status_code)
            _CORP_MAP = {}
            return _CORP_MAP
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
            xml_bytes = zf.read(name)
        cache_path.write_bytes(xml_bytes)

    _CORP_MAP = parse_corp_code_xml(xml_bytes)
    log.info("dart_corp_map_loaded", count=len(_CORP_MAP))
    return _CORP_MAP


async def fetch_kr_disclosures(
    ticker: Ticker, *, days: int = 14, page_count: int = 20
) -> list[Disclosure]:
    settings = get_settings()
    if not settings.dart_api_key:
        return []

    corp_map = await load_corp_map()
    corp_code = corp_map.get(ticker.symbol)
    if not corp_code:
        log.warning("dart_corp_code_not_found", symbol=ticker.symbol)
        return []

    async def _do() -> list[Disclosure]:
        bgn_de = (datetime.utcnow() - timedelta(days=days)).strftime("%Y%m%d")
        resp = await fetch_with_retry(
            _LIST_URL,
            params={
                "crtfc_key": settings.dart_api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "page_count": page_count,
            },
        )
        if resp.status_code != 200:
            log.warning("dart_list_non_200", status=resp.status_code)
            return []
        return parse_list_json(resp.json(), ticker)

    return await _DISCLOSURE_CACHE.get_or_fetch(
        f"disc:{ticker.key}:{days}", _do
    )


# 순전히 심볼 유효성 확인용. 테스트/외부에서 쓸 수 있게 노출.
_TICKER_CODE_RE = re.compile(r"^\d{6}$")


def is_valid_kr_symbol(s: str) -> bool:
    return bool(_TICKER_CODE_RE.match(s))
