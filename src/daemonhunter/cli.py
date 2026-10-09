import argparse
import getpass
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_urlsafe

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.exc import StaleDataError

from daemonhunter.auth import hash_password
from daemonhunter.config import DATABASE_URL
from daemonhunter.database import (
        SessionFactory,
        engine,
        is_sqlite_busy_error,
        prepare_database_storage,
        )
from daemonhunter.models import User


# Helper functions
class FactoryResetError(Exception):
    pass


def quote_identifier(identifier: str) -> str:
    escaped_identifier = identifier.replace('\"', '\"\"')
    return f'"{escaped_identifier}"'

# end of helper functions


def prompt_for_password() -> str:
    password = getpass.getpass("New Password: ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match")

    if len(password) < 12:
        raise SystemExit(
                "Password must contain at least 12 characters"
                )

    if len(password) > 128:
        raise SystemExit(
                "Password must not exceed 128 characters"
                )

    return password


def reset_owner_password() -> None:
    password = prompt_for_password()

    prepare_database_storage()

    with SessionFactory() as session:
        try:
            statement = select(User).where(User.role == "owner")
            owner = session.scalar(statement)

            if owner is None:
                raise SystemExit("No owner account exists.")

            owner.password_hash = hash_password(password)
            owner.session_secret = token_urlsafe(32)
            owner.active = True
            owner.must_change_password = False

            session.commit()

        except StaleDataError as error:
            session.rollback()

            raise SystemExit(
                    "Owner account was modified concurrently. Try again."
                    ) from error

        except OperationalError as error:
            session.rollback()

            if not is_sqlite_busy_error(error):
                raise

            raise SystemExit(
                    "Could not lock the database. Stop DaemonHunter "
                    "and try again."
                    ) from error

    print("Owner password reset. Existing sessions were logged out.")


def database_path() -> Path:
    url = make_url(DATABASE_URL)

    if url.get_backend_name() != "sqlite":
        raise SystemExit(
                "Factory reset currently supports SQLite only."
        )

    if not url.database or url.database == ":memory:":
        raise SystemExit(
                "Factory reset requires a file-based SQLite database."
                )

    return Path(url.database).resolve()


def run_migrations() -> None:
    config_path = Path("alembic.ini").resolve()

    if not config_path.exists():
        raise SystemExit(
                "alembic.ini was not found. Run this command from "
                "the Daemonhunter project directory."
                )

    alembic_config = Config(str(config_path))
    command.upgrade(alembic_config, "head")


def check_database_integrity(
        connection: sqlite3.Connection,
        ) -> None:
    integrity_rows = connection.execute(
            "PRAGMA integrity_check"
            ).fetchall()

    if integrity_rows != [("ok",)]:
        raise FactoryResetError(
                "Database integrity check failed"
                )

    foreign_key_rows = connection.execute(
            "PRAGMA foreign_key_check"
            ).fetchall()

    if foreign_key_rows:
        raise FactoryResetError(
                "Database contains foreign-key violations"
                )


def application_tables(
        connection: sqlite3.Connection,
        ) -> list[str]:
    table_rows = connection.execute(
            """
            SELECT name, sql
            FROM sqlite_schema
            WHERE type = 'table'
            ORDER BY name
            """
            ).fetchall()

    table_names: list[str] = []

    if "alembic_version" not in {
            name for name, _ in table_rows
            }:
        raise FactoryResetError(
                "Database is missing alembic_version"
                )

    for name, definition in table_rows:
        if name == "alembic_version" or name.startswith("sqlite_"):
            continue

        if (
                definition is not None
                and "CREATE VIRTUAL TABLE" in definition.upper()
                ):
            raise FactoryResetError(
                    f"Factory reset does not support virtual table: {name}"
                    )
        table_names.append(name)


    return table_names


def database_snapshot(
        connection: sqlite3.Connection,
        tables: list[str],
        ) -> tuple:
    schema = tuple(
            connection.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_schema
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
                ).fetchall()
        )

    revisions = tuple(
            connection.execute(
                """
                SELECT version_num
                FROM alembic_version
                ORDER BY version_num
                """
                ).fetchall()
            )

    row_counts = tuple(
            (
                table,
                connection.execute(
                    f"SELECT COUNT(*) FROM {quote_identifier(table)}"
                    ).fetchone()[0]
                )
            for table in tables
            )

    return schema, revisions, row_counts


def create_database_backup(
        source_connection: sqlite3.Connection,
        source_path: Path,
        tables: list[str],
        expected_snapshot: tuple,
        ) -> Path:
    backup_directory = source_path.parent / "backups"

    backup_directory.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
            )

    backup_directory.chmod(0o700)

    timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%d-%H%M%S-%fZ"
            )

    collision_number = 0

    while True:
        collision_suffix = (
                ""
                if collision_number == 0
                else f"-{collision_number}"
                )
        backup_path = backup_directory / (
                f"{source_path.stem}-{timestamp}"
                f"{collision_suffix}{source_path.suffix}"
                )

        try:
            file_descriptor = os.open(
                    backup_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                    )
        except FileExistsError:
            collision_number += 1
            continue

        os.close(file_descriptor)
        break

    backup_complete = False

    try:
        with closing(sqlite3.connect(backup_path)) as backup_connection:
            source_connection.backup(backup_connection)

        backup_path.chmod(0o600)

        backup_uri = f"{backup_path.as_uri()}?mode=ro"

        with closing(sqlite3.connect(
                backup_uri,
                uri=True,
                )) as backup_connection:
            check_database_integrity(backup_connection)

            backup_snapshot = database_snapshot(
                    backup_connection,
                    tables,
                    )

        if backup_snapshot != expected_snapshot:
            raise FactoryResetError(
                    "Backup does not match the source database"
                    )

        with backup_path.open("rb") as backup_file:
            os.fsync(backup_file.fileno())

        directory_descriptor = os.open(
                backup_directory,
                os.O_RDONLY,
                )

        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

        backup_complete = True
        return backup_path

    finally:
        if not backup_complete:
            backup_path.unlink(missing_ok=True)


def clear_application_data(
        connection: sqlite3.Connection,
        tables: list[str],
        expected_snapshot: tuple,
        ) -> None:
    if not connection.in_transaction:
        raise FactoryResetError(
                "Factory reset requires an active transaction"
                )

    expected_schema, expected_revisions, _ = expected_snapshot

    connection.execute("PRAGMA defer_foreign_keys=ON")

    for table in tables:
        connection.execute(
                f"DELETE FROM {quote_identifier(table)}"
                )

    check_database_integrity(connection)

    schema, revisions, row_counts = database_snapshot(
            connection,
            tables,
            )

    if schema != expected_schema:
        raise FactoryResetError(
                "Database schema changed during factory reset"
                )

    if revisions != expected_revisions:
        raise FactoryResetError(
                "Database revision changed during factory reset"
                )

    if any(row_count != 0 for _, row_count in row_counts):
        raise FactoryResetError(
                "Factory reset did not remove all application data"
                )


def factory_reset(no_backup: bool) -> None:
    db_path = database_path()

    print("Stop DaemonHunter before continuing.")
    print("This deletes every user, device, setting, and log.")

    confirmation = input(
            "Type RESET DAEMONHUNTER to continue: "
            )

    if confirmation != "RESET DAEMONHUNTER":
        raise SystemExit("Factory reset cancelled")

    engine.dispose()

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        except sqlite3.OperationalError as error:
            raise SystemExit(
                    "Could not lock the database. Stop DaemonHunter "
                    "and try again."
                    ) from error

        if no_backup:
            db_path.unlink()

        else:
            backup_directory = db_path.parent / "backups"
            backup_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                    )
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = (
                    backup_directory
                    / f"{db_path.stem}-{timestamp}{db_path.suffix}"
                    )
            db_path.replace(backup_path)

            backup_path.chmod(0o600)

            print(f"Backup created: {backup_path}")

    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{db_path}{suffix}")
        sidecar.unlink(missing_ok=True)

    run_migrations()

    print("Factory reset complete.")
    print("Start DaemonHunter and complete the first-run setup.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
            prog="daemonhunter",
            )
    subcommands = parser.add_subparsers(
            dest="command",
            required=True,
            )

    reset_password_parser = subcommands.add_parser(
            "reset-owner-password",
            help="Reset the owner password",
            )
    reset_password_parser.set_defaults(
            handler=lambda _: reset_owner_password(),
            )

    factory_reset_parser = subcommands.add_parser(
            "factory-reset",
            help="Reset all DaemonHunter data",
            )
    factory_reset_parser.add_argument(
            "--no-backup",
            action="store_true",
            help="Permanently delete the database without a backup",
            )
    factory_reset_parser.set_defaults(
            handler=lambda args: factory_reset(args.no_backup)
            )

    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
