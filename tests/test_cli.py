import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import daemonhunter.cli as cli
from daemonhunter.auth import verify_password
from daemonhunter.models import User


def create_sqlite_database(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('original')")


def replace_cli_database(
        monkeypatch: pytest.MonkeyPatch,
        database_path: Path,
        confirmation: str = "RESET DAEMONHUNTER",
        ) -> None:
    monkeypatch.setattr(
            cli,
            "DATABASE_URL",
            f"sqlite:///{database_path}",
            )
    monkeypatch.setattr(cli.engine, "dispose", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _: confirmation)


def test_password_prompt_rejects_mismatched_passwords(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    responses = iter([
            "first secure password",
            "different secure password",
            ])
    monkeypatch.setattr(
            cli.getpass,
            "getpass",
            lambda _: next(responses),
            )

    with pytest.raises(SystemExit, match="Passwords do not match"):
        cli.prompt_for_password()


def test_password_prompt_rejects_short_password(
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    responses = iter(["too short", "too short"])
    monkeypatch.setattr(
            cli.getpass,
            "getpass",
            lambda _: next(responses),
            )

    with pytest.raises(SystemExit, match="at least 12 characters"):
        cli.prompt_for_password()


def test_reset_owner_password_invalidates_existing_session(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    with test_session_factory() as session:
        owner = session.scalar(
                select(User).where(User.role == "owner"),
                )
        assert owner is not None
        old_session_secret = owner.session_secret

    monkeypatch.setattr(cli, "SessionFactory", test_session_factory)
    monkeypatch.setattr(
            cli,
            "prompt_for_password",
            lambda: "replacement owner password",
            )

    cli.reset_owner_password()

    with test_session_factory() as session:
        owner = session.scalar(
                select(User).where(User.role == "owner"),
                )
        assert owner is not None
        assert verify_password(
                "replacement owner password",
                owner.password_hash,
                )
        assert owner.session_secret != old_session_secret
        assert owner.active is True
        assert owner.must_change_password is False

    assert admin_client.get("/api/v1/auth/me").status_code == 401


def test_reset_owner_password_reports_stale_owner(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ) -> None:
    stale_session = test_session_factory()
    stale_owner = stale_session.scalar(
            select(User).where(User.role == "owner"),
            )

    assert stale_owner is not None

    owner_id = stale_owner.id
    stale_session.commit()

    with test_session_factory() as concurrent_session:
        current_owner = concurrent_session.get(User, owner_id)

        assert current_owner is not None

        current_owner.active = False
        current_owner.session_secret = "concurrent-session-secret"
        concurrent_session.commit()

    monkeypatch.setattr(cli, "SessionFactory", lambda: stale_session)
    monkeypatch.setattr(
            cli,
            "prompt_for_password",
            lambda: "replacement owner password",
            )
    monkeypatch.setattr(
            cli,
            "hash_password",
            lambda _: "replacement-password-hash",
            )

    with pytest.raises(
            SystemExit,
            match="Owner account was modified concurrently. Try again.",
            ):
        cli.reset_owner_password()

    assert "Owner password reset" not in capsys.readouterr().out

    with test_session_factory() as session:
        saved_owner = session.get(User, owner_id)

        assert saved_owner is not None
        assert saved_owner.active is False
        assert saved_owner.session_secret == "concurrent-session-secret"
        assert saved_owner.password_hash != "replacement-password-hash"


def test_reset_owner_password_reports_busy_database(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ) -> None:
    with (
            test_session_factory() as locking_session,
            test_session_factory() as contending_session,
            ):
        locking_owner = locking_session.scalar(
                select(User).where(User.role == "owner"),
                )

        assert locking_owner is not None

        owner_id = locking_owner.id
        original_username = locking_owner.username
        original_password_hash = locking_owner.password_hash
        original_session_secret = locking_owner.session_secret

        contending_session.connection().exec_driver_sql(
                "PRAGMA busy_timeout = 0",
                )

        locking_owner.username = "uncommitted-owner-name"
        locking_session.flush()

        monkeypatch.setattr(
                cli,
                "SessionFactory",
                lambda: contending_session,
                )
        monkeypatch.setattr(
                cli,
                "prompt_for_password",
                lambda: "replacement owner password",
                )
        monkeypatch.setattr(
                cli,
                "hash_password",
                lambda _: "replacement-password-hash",
                )

        with pytest.raises(
                SystemExit,
                match=(
                    "Could not lock the database. Stop DaemonHunter "
                    "and try again."
                    ),
                ):
            cli.reset_owner_password()

        assert "Owner password reset" not in capsys.readouterr().out

        locking_session.rollback()

    with test_session_factory() as session:
        saved_owner = session.get(User, owner_id)

        assert saved_owner is not None
        assert saved_owner.username == original_username
        assert saved_owner.password_hash == original_password_hash
        assert saved_owner.session_secret == original_session_secret


def test_factory_reset_can_be_cancelled(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_sqlite_database(database_path)
    replace_cli_database(
            monkeypatch,
            database_path,
            confirmation="cancel",
            )

    with pytest.raises(SystemExit, match="Factory reset cancelled"):
        cli.factory_reset(no_backup=False)

    assert database_path.exists()


def test_factory_reset_backs_up_database_and_runs_migrations(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_sqlite_database(database_path)
    replace_cli_database(monkeypatch, database_path)

    def create_fresh_database() -> None:
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE migrated (id INTEGER)")

    monkeypatch.setattr(cli, "run_migrations", create_fresh_database)

    cli.factory_reset(no_backup=False)

    backups = list((tmp_path / "backups").glob("daemonhunter-*.db"))
    assert len(backups) == 1
    assert database_path.exists()

    with sqlite3.connect(backups[0]) as connection:
        value = connection.execute(
                "SELECT value FROM marker",
                ).fetchone()
    with sqlite3.connect(database_path) as connection:
        migrated_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'migrated'",
                ).fetchone()

    assert value == ("original",)
    assert migrated_table == ("migrated",)


def test_factory_reset_without_backup_deletes_original_database(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_sqlite_database(database_path)
    replace_cli_database(monkeypatch, database_path)

    def create_fresh_database() -> None:
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE migrated (id INTEGER)")

    monkeypatch.setattr(cli, "run_migrations", create_fresh_database)

    cli.factory_reset(no_backup=True)

    assert database_path.exists()
    assert not (tmp_path / "backups").exists()

    with sqlite3.connect(database_path) as connection:
        original_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'marker'",
                ).fetchone()
        migrated_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'migrated'",
                ).fetchone()

    assert original_table is None
    assert migrated_table == ("migrated",)


def test_cli_parser_accepts_no_backup_flag() -> None:
    arguments = cli.build_parser().parse_args([
            "factory-reset",
            "--no-backup",
            ])

    assert arguments.no_backup is True


def create_factory_reset_database(
        database_path: Path,
        ) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
                """
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) NOT NULL
                )
                """
                )
        connection.execute(
                """
                INSERT INTO alembic_version
                VALUES ('4330f8209266')
                """
                )
        connection.execute(
                """
                CREATE TABLE devices (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
                )
        connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL
                )
                """
                )
        connection.execute(
                """
                INSERT INTO devices VALUES (1, 'server')
                """
                )
        connection.execute(
                """
                INSERT INTO users VALUES (1, 'owner')
                """
                )


def test_discovers_application_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_factory_reset_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = cli.application_tables(connection)

    assert tables == ["devices", "users"]


def test_database_snapshot_captures_revision_and_row_counts(
        tmp_path: Path,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_factory_reset_database(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = cli.application_tables(connection)
        schema, revisions, row_counts = cli.database_snapshot(
                connection,
                tables,
                )

    assert schema
    assert revisions == (("4330f8209266",),)
    assert row_counts == (
            ("devices", 1),
            ("users", 1),
            )


def test_database_integrity_accepts_valid_database(
        tmp_path: Path,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_factory_reset_database(database_path)

    with sqlite3.connect(database_path) as connection:
        cli.check_database_integrity(connection)


def test_application_tables_requires_alembic_revision(
        tmp_path: Path,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_sqlite_database(database_path)

    with sqlite3.connect(database_path) as connection:
        with pytest.raises(
                cli.FactoryResetError,
                match="missing alembic_version",
                ):
            cli.application_tables(connection)


def test_database_backup_matches_source_with_secure_permissions(
        tmp_path: Path,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_factory_reset_database(database_path)

    with closing(sqlite3.connect(database_path)) as connection:
        tables = cli.application_tables(connection)
        expected_snapshot = cli.database_snapshot(
                connection,
                tables,
                )
        backup_path = cli.create_database_backup(
                connection,
                database_path,
                tables,
                expected_snapshot,
                )

    backup_uri = f"{backup_path.as_uri()}?mode=ro"

    with closing(sqlite3.connect(
            backup_uri,
            uri=True,
            )) as backup_connection:
        backup_snapshot = cli.database_snapshot(
                backup_connection,
                tables,
                )

    assert backup_snapshot == expected_snapshot
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_path.parent.stat().st_mode) == 0o700


def test_database_backup_includes_committed_wal_rows(
        tmp_path: Path,
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"
    create_factory_reset_database(database_path)

    with closing(sqlite3.connect(database_path)) as connection:
        journal_mode = connection.execute(
                "PRAGMA journal_mode=WAL"
                ).fetchone()
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
                "INSERT INTO devices VALUES (2, 'wal-device')"
                )
        connection.commit()

        assert journal_mode == ("wal",)
        assert Path(f"{database_path}-wal").exists()

        tables = cli.application_tables(connection)
        expected_snapshot = cli.database_snapshot(
                connection,
                tables,
                )
        backup_path = cli.create_database_backup(
                connection,
                database_path,
                tables,
                expected_snapshot,
                )

    backup_uri = f"{backup_path.as_uri()}?mode=ro"

    with closing(sqlite3.connect(
            backup_uri,
            uri=True,
            )) as backup_connection:
        device_names = backup_connection.execute(
                "SELECT name FROM devices ORDER BY id"
                ).fetchall()

    assert device_names == [("server",), ("wal-device",)]


def test_database_backup_does_not_overwrite_name_collision(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return cls(
                    2026,
                    10,
                    7,
                    12,
                    30,
                    tzinfo=timezone.utc,
                    )

    database_path = tmp_path / "daemonhunter.db"
    create_factory_reset_database(database_path)
    monkeypatch.setattr(cli, "datetime", FixedDatetime)

    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    existing_backup = (
            backup_directory
            / "daemonhunter-20261007-123000-000000Z.db"
            )
    existing_backup.write_bytes(b"existing backup")

    with closing(sqlite3.connect(database_path)) as connection:
        tables = cli.application_tables(connection)
        expected_snapshot = cli.database_snapshot(
                connection,
                tables,
                )
        backup_path = cli.create_database_backup(
                connection,
                database_path,
                tables,
                expected_snapshot,
                )

    assert backup_path.name == (
            "daemonhunter-20261007-123000-000000Z-1.db"
            )
    assert backup_path.exists()
    assert existing_backup.read_bytes() == b"existing backup"
