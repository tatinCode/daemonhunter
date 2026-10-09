import argparse
import getpass
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_urlsafe

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


def open_database_for_reset(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit("Database file not found")
    if not db_path.is_file():
        raise SystemExit("Factory reset requires a regular database file")

    connection = sqlite3.connect(
            db_path.as_uri(),
            uri=True,
            isolation_level=None,
            timeout=5.0,
            )

    # KNOWN GAP: if either PRAGMA below raises, `connection` is never
    # returned, so factory_reset's `connection = ...` assignment never
    # completes and its `finally: connection.close()` cannot reach it.
    # Today that costs nothing — factory_reset turns the error into
    # SystemExit, main() does not catch it, and the process exits — but
    # the handle is never explicitly released.
    #
    # Fix idea: split creation from validation so the assignment always
    # completes before anything can fail:
    #     connection = open_database_for_reset(db_path)  # connect only
    #     validate_database_for_reset(connection)        # run PRAGMAs
    #
    # Hard to test: sqlite3.Connection is a C type with no __dict__, so
    # `connection.close = ...` raises AttributeError ("attribute 'close'
    # is read-only") and the connection is unreachable from outside. The
    # alternatives (counting /proc/self/fd, probing file locks, or a
    # forwarding proxy for a patched sqlite3.connect) are all worse than
    # the bug.
    connection.execute("PRAGMA foreign_keys=ON")

    journal_mode = connection.execute(
            "PRAGMA journal_mode",
            ).fetchone()[0]

    if journal_mode == "off":
        connection.close()
        raise FactoryResetError(
                "Factory reset requires SQLite journaling"
                )

    return connection


def is_sqlite_lock_error(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)

    if isinstance(code, int) and (code & 0xFF) in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
            ):
        return True

    message = str(error).lower()

    return "locked" in message


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

    expected_confirmation = (
            "RESET DAEMONHUNTER WITHOUT BACKUP"
            if no_backup
            else "RESET DAEMONHUNTER"
            )

    print("Stop DaemonHunter before continuing.")
    print("This deletes every user, device, setting, and log.")

    prompt = f"Type {expected_confirmation} to continue: "

    if input(prompt) != expected_confirmation:
        raise SystemExit("Factory reset cancelled")

    engine.dispose()

    connection = None
    backup_path = None

    try:
        connection = open_database_for_reset(db_path)
        check_database_integrity(connection)

        tables = application_tables(connection)
        expected_snapshot = database_snapshot(connection, tables)
        data_version_before = connection.execute(
                "PRAGMA data_version"
                ).fetchone()[0]

        if not no_backup:
            backup_path = create_database_backup(
                    connection,
                    db_path,
                    tables,
                    expected_snapshot,
                    )

        connection.execute("BEGIN EXCLUSIVE")

        if not no_backup:
            data_version_after = connection.execute(
                    "PRAGMA data_version"
                    ).fetchone()[0]

            if data_version_after != data_version_before:
                raise FactoryResetError(
                        "Database changed during backup. Try again."
                        )

        clear_application_data(
                connection,
                tables,
                expected_snapshot,
                )

        connection.commit()

    except FactoryResetError as error:
        if connection is not None and connection.in_transaction:
            connection.rollback()

        raise SystemExit(str(error)) from error

    except sqlite3.OperationalError as error:
        if connection is not None and connection.in_transaction:
            connection.rollback()

        if not is_sqlite_lock_error(error):
            raise

        raise SystemExit(
                "Could not lock the database. Stop DaemonHunter "
                "and try again."
                ) from error
    finally:
        if connection is not None:
            connection.close()

    if backup_path is not None:
        print(f"Backup created: {backup_path}")

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
            help="Reset the database without a backup",
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
