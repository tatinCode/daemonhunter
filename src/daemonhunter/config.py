import os

DATABASE_URL = os.getenv(
        "DAEMONHUNTER_DATABASE_URL",
        "sqlite:///./daemonhunter.db",
        )
