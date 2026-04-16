"""Shared pytest fixtures for the Peblar test suite."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity's exponential backoff instant during tests.

    Tenacity sleeps via ``await asyncio.sleep(...)``; we swap that for a
    zero-delay version so the real retry logic still exercises, just
    without the exponential wall-clock cost.
    """
    real_sleep = asyncio.sleep

    async def instant_sleep(_delay: float, result: Any = None) -> Any:
        return await real_sleep(0, result)

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
