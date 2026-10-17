import http.client
import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request

from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
            self,
            request,
            response,
            code,
            message,
            headers,
            new_url,
            ):
        return None


def metrics_endpoint(server_url: str) -> str:
    if not isinstance(server_url, str) or not server_url.strip():
        raise ValueError("Server URL cannot be empty")

    server_url = server_url.strip()

    if any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            for character in server_url
            ):
        raise ValueError(
                "Server URL must not contain whitespace or control characters"
                )

    try:
        parsed = urllib.parse.urlsplit(server_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Server URL is invalid") from error

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
                "Server URL must be an absolute HTTP or HTTPS URL"
                )

    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
                "Server URL must not contain credentials; use the agent_token"
                )

    if parsed.query or parsed.fragment:
        raise ValueError(
                "Server URL must not contain a query string or fragment"
                )

    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Server URL port must be between 1 and 65535")

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/") + "/api/v1/agent/metrics",
        "",
        "",
        ))


def report_metrics(
        metrics: Mapping[str, Any],
        server_url: str,
        agent_token: str,
        timeout: float = DEFAULT_TIMEOUT
        ) -> bool:
    endpoint = metrics_endpoint(server_url)

    if (
            not isinstance(agent_token, str)
            or not agent_token
            or not agent_token.isascii()
            or any(
                character.isspace()
                or ord(character) < 32
                or ord(character) == 127
                for character in agent_token
                )
            ):
        raise ValueError(
                "Agent token must be nonempty ASCII without whitespace "
                "or control characters"
                )

    if isinstance(timeout, bool):
        raise ValueError("Timeout must be a finite positive number")

    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
                "Timeout must be a finite positive number"
                ) from error

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Timeout must be a finite positive number")

    if not isinstance(metrics, Mapping):
        raise TypeError("Metrics must be a mapping")

    payload = json.dumps(
            dict(metrics),
            allow_nan=False
            ).encode("utf-8")

    request = urllib.request.Request(
            url=endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {agent_token}",
                },
            method="POST",
            )

    opener = urllib.request.build_opener(NoRedirectHandler())

    try:
        with opener.open(
                request,
                timeout=timeout_seconds,
                ) as response:
            if 200 <= response.status < 300:
                return True

            logger.warning(
                    "Metrics report rejected: HTTP %s",
                    response.status,
                    )

    except urllib.error.HTTPError as error:
        with error:
            logger.warning(
                    "Metrics report failed: HTTP %s",
                    error.code,
                    )

    except (
            urllib.error.URLError,
            OSError,
            http.client.HTTPException,
            ) as error:
        logger.warning(
                "Could not deliver metrics to DaemonHunter: %s",
                error,
                )

    return False
