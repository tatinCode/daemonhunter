import os
from pathlib import Path
from secrets import token_urlsafe


def resolve_default_database_path(
        xdg_data_home: str | None,
        home_directory: Path,
        ) -> Path:
    data_home = (
            Path(xdg_data_home).expanduser()
            if xdg_data_home
            else home_directory / ".local" / "share"
            )

    if not data_home.is_absolute():
        data_home = home_directory / ".local" / "share"

    return data_home / "daemonhunter" / "daemonhunter.db"


def resolve_database_url(
        configured_database_url: str | None,
        default_database_path: Path,
        ) -> str:
    if configured_database_url is not None:
        return configured_database_url

    return f"sqlite:///{default_database_path}"


DEFAULT_DATABASE_PATH = resolve_default_database_path(
        os.getenv("XDG_DATA_HOME"),
        Path.home(),
        )

configured_database_url = os.getenv(
        "DAEMONHUNTER_DATABASE_URL",
        )

USING_DEFAULT_DATABASE = configured_database_url is None

DATABASE_URL = resolve_database_url(
        configured_database_url,
        DEFAULT_DATABASE_PATH,
        )

COOKIE_SECURE = os.getenv(
        "DAEMONHUNTER_COOKIE_SECURE",
        "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
configured_setup_token = os.getenv(
        "DAEMONHUNTER_SETUP_TOKEN",
        )


LOGIN_RATE_LIMIT_ATTEMPTS = int(
        os.getenv(
            "DAEMONHUNTER_LOGIN_RATE_LIMIT_ATTEMPTS",
            "5",
            )
        )

LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(
        os.getenv(
            "DAEMONHUNTER_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
            "300",
            )
        )

TRUST_PROXY_HEADERS = os.getenv(
        "DAEMONHUNTER_TRUST_PROXY_HEADERS",
        "false",
        ).strip().lower() in {"1", "true", "yes", "on"}


if configured_setup_token is None:
    SETUP_TOKEN = token_urlsafe(32)
    SETUP_TOKEN_WAS_GENERATED = True

else:
    SETUP_TOKEN = configured_setup_token.strip()
    SETUP_TOKEN_WAS_GENERATED = False

    if len(SETUP_TOKEN) < 32:
        raise RuntimeError(
                "DAEMONHUNTER_SETUP_TOKEN must contain "
                "at least 32 characters"
                )
