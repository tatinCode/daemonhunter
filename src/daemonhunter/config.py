import os

DATABASE_URL = os.getenv(
        "DAEMONHUNTER_DATABASE_URL",
        "sqlite:///./daemonhunter.db",
        )

COOKIE_SECURE = os.getenv(
        "DAEMONHUNTER_COOKIE_SECURE",
        "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
