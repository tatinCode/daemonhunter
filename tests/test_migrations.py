import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import daemonhunter.config as config_module


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

HEAD_REVISION = "4330f8209266"


def test_upgrade_head_creates_expected_schema(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = tmp_path / "migrated.db"

    # migrations/env.py overwrites alembic's sqlalchemy.url with
    # daemonhunter.config.DATABASE_URL, so the Alembic Config object
    # cannot point the upgrade at a temporary file.
    monkeypatch.setattr(
            config_module,
            "DATABASE_URL",
            f"sqlite:///{database_path}",
            )

    alembic_config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'",
                    )
                }
        revision = connection.execute(
                "SELECT version_num FROM alembic_version",
                ).fetchone()[0]
        user_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(users)")
                }
        device_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(devices)")
                }

    assert revision == HEAD_REVISION
    assert {"alembic_version", "devices", "users"} <= tables
    assert "version_id" in user_columns
    assert {"guest_visible", "host", "name"} <= device_columns
