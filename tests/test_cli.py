import sqlite3
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
