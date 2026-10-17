import http.client
import io
import json
import logging
import threading
import urllib.error
from collections import UserDict
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType
from typing import Any

import pytest

from daemonhunter.agent import reporter


SERVER_URL = "https://monitor.example"
TOKEN = "agent-test-only-token"
METRICS = {"hostname": "test-server", "cpu_percent": 25.5, "temperature_celsius": None}


class StubResponse(io.BytesIO):
    def __init__(self, status: int = 200) -> None:
        super().__init__(b"")
        self.status = status


class StubOpener:
    def __init__(self) -> None:
        self.response = StubResponse()
        self.error: Exception | None = None
        self.calls: list[tuple[Any, float]] = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> StubOpener:
    transport = StubOpener()
    monkeypatch.setattr(reporter.urllib.request, "build_opener", lambda *handlers: transport)
    return transport


@pytest.mark.parametrize("base, expected", [
        ("http://monitor.example", "http://monitor.example/api/v1/agent/metrics"),
        ("https://monitor.example/", "https://monitor.example/api/v1/agent/metrics"),
        ("https://monitor.example/daemonhunter/", "https://monitor.example/daemonhunter/api/v1/agent/metrics"),
        ("  http://127.0.0.1:8000/base///  ", "http://127.0.0.1:8000/base/api/v1/agent/metrics"),
        ("http://[::1]:8000/base", "http://[::1]:8000/base/api/v1/agent/metrics"),
        ("https://monitor.example:65535", "https://monitor.example:65535/api/v1/agent/metrics"),
        ])
def test_metrics_endpoint_accepts_base_urls_and_preserves_prefix(base: str, expected: str) -> None:
    assert reporter.metrics_endpoint(base) == expected


@pytest.mark.parametrize("base", [
        None, "", "  ", "monitor.example", "/relative", "https:monitor.example",
        "ftp://monitor.example", "http:///missing-host", "http://[::1",
        "http://monitor.example:invalid", "http://monitor.example:0",
        "http://monitor.example:65536", "http://user:password@monitor.example",
        "http://@monitor.example", "http://monitor.example?token=value",
        "http://monitor.example#fragment", "http://mon itor.example",
        "http://monitor.example/\nmetrics", "http://monitor.example/\x00metrics",
        "http://monitor.example/\x7fmetrics",
        ])
def test_metrics_endpoint_rejects_invalid_configuration(base) -> None:
    with pytest.raises(ValueError):
        reporter.metrics_endpoint(base)


def test_report_posts_json_authorization_and_custom_timeout(opener: StubOpener) -> None:
    assert reporter.report_metrics(METRICS, SERVER_URL + "/base/", TOKEN, timeout=2.5) is True

    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url == SERVER_URL + "/base/api/v1/agent/metrics"
    assert request.get_method() == "POST"
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["content-type"] == "application/json"
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.data.decode("utf-8")) == METRICS
    assert timeout == 2.5
    assert opener.response.closed


@pytest.mark.parametrize("mapping", [UserDict, MappingProxyType])
def test_report_accepts_non_dict_mappings_and_unicode(opener: StubOpener, mapping) -> None:
    metrics = mapping({"hostname": "serveur-café", "memory_total": 8589934592})

    assert reporter.report_metrics(metrics, SERVER_URL, TOKEN) is True

    request, timeout = opener.calls[0]
    assert json.loads(request.data.decode("utf-8")) == dict(metrics)
    assert timeout == 5


@pytest.mark.parametrize("status", [200, 202, 204, 299])
def test_successful_response_is_closed(opener: StubOpener, status: int) -> None:
    opener.response = StubResponse(status)

    assert reporter.report_metrics(METRICS, SERVER_URL, TOKEN) is True
    assert opener.response.closed


@pytest.mark.parametrize("status", [199, 300, 500])
def test_unexpected_response_status_returns_false_and_closes_response(
        opener: StubOpener,
        status: int,
        caplog: pytest.LogCaptureFixture,
        ) -> None:
    opener.response = StubResponse(status)

    with caplog.at_level(logging.WARNING, logger=reporter.__name__):
        assert reporter.report_metrics(METRICS, SERVER_URL, TOKEN) is False

    assert opener.response.closed
    assert str(status) in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_http_error_is_reported_and_its_body_is_closed(
        opener: StubOpener,
        status: int,
        caplog: pytest.LogCaptureFixture,
        ) -> None:
    body = io.BytesIO(b"server rejection details")
    opener.error = urllib.error.HTTPError(
            SERVER_URL + "/api/v1/agent/metrics", status, "Rejected", None, body,
            )

    with caplog.at_level(logging.WARNING, logger=reporter.__name__):
        assert reporter.report_metrics(METRICS, SERVER_URL, TOKEN) is False

    assert body.closed
    assert str(status) in caplog.text
    assert TOKEN not in caplog.text
    assert "server rejection details" not in caplog.text


@pytest.mark.parametrize("error", [
        urllib.error.URLError("DNS resolution failed"),
        TimeoutError("Socket timed out"),
        ConnectionRefusedError("Connection refused"),
        ConnectionResetError("Connection reset"),
        OSError("Network unavailable"),
        http.client.BadStatusLine("Malformed HTTP status"),
        ])
def test_delivery_failures_return_false_without_logging_credentials(
        opener: StubOpener,
        error: Exception,
        caplog: pytest.LogCaptureFixture,
        ) -> None:
    opener.error = error

    with caplog.at_level(logging.WARNING, logger=reporter.__name__):
        assert reporter.report_metrics(METRICS, SERVER_URL, TOKEN) is False

    assert len(opener.calls) == 1
    assert caplog.records
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("token", [
        None, 42, "", " ", " leading", "trailing ", "token\nnewline",
        "token\x00bad", "token\x7f", "tökén",
        ])
def test_invalid_tokens_are_rejected_before_delivery(opener: StubOpener, token) -> None:
    with pytest.raises(ValueError):
        reporter.report_metrics(METRICS, SERVER_URL, token)
    assert opener.calls == []


@pytest.mark.parametrize("timeout", [
        True, False, 0, -1, float("nan"), float("inf"), -float("inf"),
        None, "invalid", 10**400,
        ])
def test_invalid_timeouts_are_rejected_before_delivery(opener: StubOpener, timeout) -> None:
    with pytest.raises(ValueError):
        reporter.report_metrics(METRICS, SERVER_URL, TOKEN, timeout=timeout)
    assert opener.calls == []


def test_invalid_server_url_is_rejected_before_delivery(opener: StubOpener) -> None:
    with pytest.raises(ValueError):
        reporter.report_metrics(METRICS, "/relative", TOKEN)
    assert opener.calls == []


@pytest.mark.parametrize("metrics", [None, [], 42])
def test_non_mapping_payloads_are_rejected_before_delivery(opener: StubOpener, metrics) -> None:
    with pytest.raises(TypeError):
        reporter.report_metrics(metrics, SERVER_URL, TOKEN)
    assert opener.calls == []


@pytest.mark.parametrize("metrics, expected_error", [
        ({"value": float("nan")}, ValueError),
        ({"value": float("inf")}, ValueError),
        ({"values": [-float("inf")]}, ValueError),
        ({"value": object()}, TypeError),
        ])
def test_invalid_json_payloads_are_rejected_before_delivery(
        opener: StubOpener,
        metrics: dict,
        expected_error: type[Exception],
        ) -> None:
    with pytest.raises(expected_error):
        reporter.report_metrics(metrics, SERVER_URL, TOKEN)
    assert opener.calls == []


@pytest.fixture
def metrics_server(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple, None, None]:
    # Exercise real urllib behavior only against loopback, never an external proxy.
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    received: list[dict] = []
    settings: dict[str, Any] = {"status": 202, "location": None}

    class Handler(BaseHTTPRequestHandler):
        def record_request(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            received.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": self.rfile.read(length),
                    })

        def do_POST(self) -> None:
            self.record_request()
            self.send_response(settings["status"])
            if settings["location"]:
                self.send_header("Location", settings["location"])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            # A mistakenly redirected POST would arrive here and appear successful.
            self.record_request()
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": .01},
                daemon=True,
                )
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", received, settings
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive(), "Loopback HTTP test server did not stop"


def test_real_http_delivery_sends_authenticated_json(metrics_server) -> None:
    root, received, _ = metrics_server

    assert reporter.report_metrics(METRICS, root, TOKEN, timeout=2) is True

    assert len(received) == 1
    request = received[0]
    assert request["method"] == "POST"
    assert request["path"] == "/api/v1/agent/metrics"
    assert request["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert request["headers"]["content-type"] == "application/json"
    assert json.loads(request["body"].decode("utf-8")) == METRICS


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_real_redirect_never_follows_or_converts_post_to_get(metrics_server, status: int) -> None:
    root, received, settings = metrics_server
    settings.update(status=status, location="/redirect-target")

    assert reporter.report_metrics(METRICS, root, TOKEN, timeout=2) is False

    assert len(received) == 1
    assert received[0]["method"] == "POST"
    assert received[0]["path"] == "/api/v1/agent/metrics"
