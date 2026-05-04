"""Tests for rate limiter and etsy_request HTTP wrapper."""

import asyncio
import time

import pytest

from etsy_mcp.http import RateLimiter


async def test_rate_limiter_allows_burst_up_to_capacity():
    rl = RateLimiter(rate_per_second=10, capacity=10)
    start = time.monotonic()
    for _ in range(10):
        await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05  # 10 acquires from a full bucket should be near-instant


async def test_rate_limiter_throttles_when_empty():
    rl = RateLimiter(rate_per_second=10, capacity=2)
    # Drain the bucket
    await rl.acquire()
    await rl.acquire()
    # Next acquire must wait ~100ms (1 token at 10/s)
    start = time.monotonic()
    await rl.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08  # allow ~20ms slack for scheduler
