"""공용 async HTTP client + TTL 메모리 캐시 + AsyncRateLimiter.

- 모든 외부 소스는 이 client를 통해 호출한다 (User-Agent 일관, 타임아웃 통일).
- 캐시는 프로세스 메모리. SQLite 영속 캐시는 필요 시 store.py 쪽에 붙인다.
- RateLimiter: KIS처럼 연속 호출에 민감한 API 앞단에서 최소 간격을 보장.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


# ─── AsyncRateLimiter ───


class AsyncRateLimiter:
    """직전 `acquire()` 완료 시각으로부터 `min_gap_seconds` 가 지나도록 sleep한다.
    coroutine-safe (asyncio.Lock). 추적 시각은 `time.monotonic()` 기반 — 월클럭 변동에 무관.
    """

    def __init__(self, min_gap_seconds: float) -> None:
        if min_gap_seconds < 0:
            raise ValueError("min_gap_seconds must be >= 0")
        self._min_gap = float(min_gap_seconds)
        self._last = 0.0
        self._lock = asyncio.Lock()

    @property
    def min_gap(self) -> float:
        return self._min_gap

    async def acquire(self) -> None:
        async with self._lock:
            if self._min_gap > 0:
                now = time.monotonic()
                wait = self._min_gap - (now - self._last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last = time.monotonic()

from mimmy.config import get_settings
from mimmy.logging import get_logger

log = get_logger(__name__)

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """프로세스 전역 AsyncClient. lazy 초기화."""
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                s = get_settings()
                _client = httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0),
                    headers={
                        "User-Agent": s.http_user_agent,
                        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                    },
                    follow_redirects=True,
                )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def fetch_with_retry(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    """네트워크 에러/5xx에 대해 3회 지수 백오프."""
    client = await get_client()

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError, httpx.TimeoutException)
        ),
        reraise=True,
    ):
        with attempt:
            resp = await client.request(
                method, url, params=params, headers=headers, content=content
            )
            if resp.status_code >= 500:
                resp.raise_for_status()
            return resp
    raise RuntimeError("unreachable")


# ─── TTL 메모리 캐시 ───


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, default_ttl: float = 60.0) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.time() + (ttl if ttl is not None else self._default_ttl),
        )

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        ttl: float | None = None,
    ) -> Any:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = await fetcher()
        self.set(key, value, ttl)
        return value
