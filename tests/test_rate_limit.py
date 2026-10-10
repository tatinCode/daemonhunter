from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import daemonhunter.rate_limit as rate_limit
from daemonhunter.rate_limit import SlidingWindowLimiter


def test_failures_expire_and_retry_after_tracks_the_window(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    now = [1000.0]
    monkeypatch.setattr(rate_limit, "monotonic", lambda: now[0])
    limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=300)

    with limiter.attempt("first") as attempt:
        attempt.fail()

    now[0] = 1010.0
    with limiter.attempt("first") as attempt:
        attempt.fail()

    now[0] = 1020.0
    with pytest.raises(HTTPException) as blocked:
        with limiter.attempt("first"):
            pytest.fail("A third attempt must not run")

    assert blocked.value.status_code == 429
    assert blocked.value.headers == {"Retry-After": "280"}

    now[0] = 1300.0
    with limiter.attempt("first"):
        pass

    assert list(limiter._failures["first"]) == [1010.0]


def test_cleanup_removes_abandoned_keys_and_successes_leave_no_state(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    now = [1000.0]
    monkeypatch.setattr(rate_limit, "monotonic", lambda: now[0])
    limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=300)

    with limiter.attempt("abandoned") as attempt:
        attempt.fail()

    for index in range(100):
        with limiter.attempt(f"successful-{index}"):
            pass

    assert set(limiter._failures) == {"abandoned"}
    assert not limiter._pending

    now[0] = 1301.0
    with limiter.attempt("new"):
        pass

    assert not limiter._failures
    assert not limiter._pending


def test_key_isolation_and_unexpected_error_releases_reservation() -> None:
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=300)

    with pytest.raises(RuntimeError, match="database failed"):
        with limiter.attempt("first"):
            raise RuntimeError("database failed")

    with limiter.attempt("first") as attempt:
        attempt.fail()

    with limiter.attempt("second"):
        pass

    with pytest.raises(HTTPException) as blocked:
        with limiter.attempt("first"):
            pytest.fail("The first key must remain blocked")

    assert blocked.value.status_code == 429
    assert not limiter._pending


@pytest.mark.parametrize("failed", [False, True])
def test_concurrent_reservations_cannot_exceed_the_limit(
        failed: bool,
        ) -> None:
    limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=300)
    entered = Barrier(6)
    release = Event()

    def hold_reservation() -> None:
        with limiter.attempt("same-ip") as attempt:
            entered.wait(timeout=10)
            assert release.wait(timeout=10)
            if failed:
                attempt.fail()

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(hold_reservation) for _ in range(5)]

        try:
            entered.wait(timeout=10)

            with pytest.raises(HTTPException) as blocked:
                with limiter.attempt("same-ip"):
                    pytest.fail("A sixth concurrent request must not run")

            assert blocked.value.status_code == 429
            assert blocked.value.headers == {"Retry-After": "1"}

        finally:
            release.set()

        for future in futures:
            future.result()

    assert not limiter._pending
    if failed:
        with pytest.raises(HTTPException) as blocked:
            with limiter.attempt("same-ip"):
                pytest.fail("Five concurrent failures must be recorded")
        assert blocked.value.status_code == 429
    else:
        with limiter.attempt("same-ip"):
            pass


def test_forwarded_ip_is_only_used_when_explicitly_trusted(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    request = Request({
            "type": "http",
            "headers": [
                (b"x-forwarded-for", b"198.51.100.5, 192.0.2.10"),
                ],
            "client": ("10.0.0.2", 12345),
            })

    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)
    assert rate_limit.client_ip(request) == "10.0.0.2"

    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
    assert rate_limit.client_ip(request) == "192.0.2.10"
