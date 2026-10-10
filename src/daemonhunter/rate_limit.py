from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status

from daemonhunter.config import (
        LOGIN_RATE_LIMIT_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        TRUST_PROXY_HEADERS,
        )


class RateLimitAttempt:
    def __init__(self) -> None:
        self.failed = False

    def fail(self) -> None:
        self.failed = True


class SlidingWindowLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        if max_attempts < 1 or window_seconds <= 0:
            raise ValueError("Rate limit and window must be positive")

        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._pending: dict[str, int] = {}
        self._lock = Lock()
        self._next_cleanup = monotonic() + 60

    def reset(self) -> None:
        # For test isolation; call only when no requests are in flight.
        with self._lock:
            if self._pending:
                raise RuntimeError("Cannot reset while attempts are pending")

            self._failures.clear()
            self._next_cleanup = monotonic() + 60

    def _prune(self, key: str, now: float) -> deque[float] | None:
        failures = self._failures.get(key)

        if failures is None:
            return None

        while failures and failures[0] <= now - self.window_seconds:
            failures.popleft()

        if not failures:
            del self._failures[key]
            return None

        return failures

    def _cleanup(self, now: float) -> None:
        for key in tuple(self._failures):
            self._prune(key, now)

    @contextmanager
    def attempt(self, key: str) -> Iterator[RateLimitAttempt]:
        now = monotonic()

        with self._lock:
            if now >= self._next_cleanup:
                self._cleanup(now)
                self._next_cleanup = now + 60

            failures = self._prune(key, now)
            pending = self._pending.get(key, 0)
            failure_count = len(failures) if failures is not None else 0

            if failure_count + pending >= self.max_attempts:
                retry_after = (
                    max(1, ceil(failures[0] + self.window_seconds - now))
                    if failures
                    else 1
                    )

                raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many attempts; try again later",
                        headers={"Retry-After": str(retry_after)},
                        )

            self._pending[key] = pending + 1

        result = RateLimitAttempt()

        try:
            yield result

        finally:
            with self._lock:
                remaining = self._pending[key] - 1

                if remaining:
                    self._pending[key] = remaining
                else:
                    del self._pending[key]

                if result.failed:
                    self._failures.setdefault(key, deque()).append(
                            monotonic(),
                            )


def client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("X-Forwarded-For")

        if forwarded_for:
            return forwarded_for.split(",")[-1].strip()

    if request.client is None:
        return "unknown"

    return request.client.host


login_limiter = SlidingWindowLimiter(
        LOGIN_RATE_LIMIT_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )


setup_limiter = SlidingWindowLimiter(
        LOGIN_RATE_LIMIT_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )
