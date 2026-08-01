"""Bounded retry helpers for transient cloud dependency failures."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    attempts: int,
    base_seconds: float,
    max_seconds: float,
    retryable: tuple[type[BaseException], ...],
    sleep: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
) -> T:
    """Execute an operation with capped exponential backoff and full jitter."""

    if attempts < 1:
        raise ValueError("attempts must be positive")
    if base_seconds < 0 or max_seconds < base_seconds:
        raise ValueError("retry delay configuration is invalid")
    for attempt in range(attempts):
        try:
            return operation()
        except retryable:
            if attempt == attempts - 1:
                raise
            cap = min(max_seconds, base_seconds * (2**attempt))
            sleep(cap * random_value())
    raise AssertionError("retry loop did not return or raise")
