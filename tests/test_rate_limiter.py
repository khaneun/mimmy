from __future__ import annotations

import asyncio
import time

import pytest

from mimmy.data.http import AsyncRateLimiter


def _run(coro):
    return asyncio.run(coro)


def test_min_gap_must_be_non_negative():
    with pytest.raises(ValueError):
        AsyncRateLimiter(-0.1)


def test_zero_gap_is_noop():
    rl = AsyncRateLimiter(0.0)

    async def go():
        t0 = time.monotonic()
        for _ in range(5):
            await rl.acquire()
        return time.monotonic() - t0

    elapsed = _run(go())
    assert elapsed < 0.05  # 0 간격이면 거의 즉시


def test_enforces_min_gap_between_acquires():
    gap = 0.05
    rl = AsyncRateLimiter(gap)

    async def go():
        await rl.acquire()  # 첫 호출은 즉시
        t0 = time.monotonic()
        await rl.acquire()
        await rl.acquire()
        return time.monotonic() - t0

    elapsed = _run(go())
    # 두 번째·세 번째 acquire 사이에 최소 gap 2회가 보장돼야 한다.
    assert elapsed >= 2 * gap - 0.005


def test_concurrent_acquires_are_serialized():
    """여러 코루틴이 동시에 acquire() 해도 gap이 지켜져야 한다."""
    gap = 0.02
    rl = AsyncRateLimiter(gap)

    async def go():
        t0 = time.monotonic()
        await asyncio.gather(*[rl.acquire() for _ in range(5)])
        return time.monotonic() - t0

    elapsed = _run(go())
    # N번 acquire → 최소 (N-1) * gap 걸린다.
    assert elapsed >= 4 * gap - 0.005
