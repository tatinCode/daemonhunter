import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import daemonhunter.config as config_module


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

PREVIOUS_REVISION = "4330f8209266"
HEAD_REVISION = "9d9937a2e4d7"


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
        event_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(device_status_events)"
                    )
                }
        foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(device_status_events)"
                ).fetchall()
        indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(device_status_events)"
                    )
                }

    assert revision == HEAD_REVISION
    assert {"alembic_version", "devices", "users", "device_status_events"} <= tables
    assert "version_id" in user_columns
    assert {"guest_visible", "host", "name", "consecutive_failures"} <= device_columns
    assert {"id", "device_id", "previous_status", "new_status", "occurred_at"} <= event_columns
    assert "ix_device_status_events_device_id_id" in indexes
    assert any(
            row[2] == "devices" and row[3] == "device_id" and row[6] == "CASCADE"
            for row in foreign_keys
            )


def test_monitoring_migration_upgrades_and_downgrades_existing_device(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = tmp_path / "existing-device.db"
    monkeypatch.setattr(
            config_module,
            "DATABASE_URL",
            f"sqlite:///{database_path}",
            )
    alembic_config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, PREVIOUS_REVISION)

    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                    """
                    INSERT INTO devices (name, host, status, guest_visible)
                    VALUES ('Existing Pi', '192.168.1.10', 'online', 1)
                    """
                    )
        original_device = connection.execute(
                """
                SELECT id, name, host, status, guest_visible, created_at, updated_at
                FROM devices
                """
                ).fetchone()

    assert original_device is not None
    command.upgrade(alembic_config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        upgraded_device = connection.execute(
                """
                SELECT id, name, host, status, guest_visible, created_at, updated_at,
                       consecutive_failures
                FROM devices
                WHERE id = ?
                """,
                (original_device[0],),
                ).fetchone()
        devices_schema = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'devices'"
                ).fetchone()[0]

        assert upgraded_device == (*original_device, 0)
        assert "ck_devices_consecutive_failures_nonnegative" in devices_schema

        with connection:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                        "UPDATE devices SET consecutive_failures = -1 WHERE id = ?",
                        (original_device[0],),
                        )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                        "INSERT INTO devices (name, host) VALUES (?, ?)",
                        ("Existing Pi", "192.168.1.11"),
                        )
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                        "INSERT INTO devices (name, host) VALUES (?, ?)",
                        ("Other Pi", "192.168.1.10"),
                        )

            deleted_device_id = connection.execute(
                    "INSERT INTO devices (name, host) VALUES (?, ?)",
                    ("Deleted Pi", "192.168.1.12"),
                    ).lastrowid
            connection.execute(
                    """
                    INSERT INTO device_status_events (
                        device_id, previous_status, new_status
                    ) VALUES (?, 'unknown', 'online')
                    """,
                    (deleted_device_id,),
                    )
            connection.execute(
                    "DELETE FROM devices WHERE id = ?",
                    (deleted_device_id,),
                    )

        assert connection.execute(
                "SELECT COUNT(*) FROM device_status_events"
                ).fetchone()[0] == 0

    command.downgrade(alembic_config, PREVIOUS_REVISION)

    with closing(sqlite3.connect(database_path)) as connection:
        revision = connection.execute(
                "SELECT version_num FROM alembic_version"
                ).fetchone()[0]
        device_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(devices)")
                }
        restored_device = connection.execute(
                """
                SELECT id, name, host, status, guest_visible, created_at, updated_at
                FROM devices
                WHERE id = ?
                """,
                (original_device[0],),
                ).fetchone()
        events_table = connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE type = 'table' AND name = 'device_status_events'
                """
                ).fetchone()

    assert revision == PREVIOUS_REVISION
    assert "consecutive_failures" not in device_columns
    assert events_table is None
    assert restored_device == original_device
