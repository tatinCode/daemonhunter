import os
from secrets import token_urlsafe

DATABASE_URL = os.getenv(
        "DAEMONHUNTER_DATABASE_URL",
        "sqlite:///./daemonhunter.db",
        )

COOKIE_SECURE = os.getenv(
        "DAEMONHUNTER_COOKIE_SECURE",
        "false",
        ).strip().lower() in {"1", "true", "yes", "on"}

configured_setup_token = os.getenv(
        "DAEMONHUNTER_SETUP_TOKEN",
        )

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
