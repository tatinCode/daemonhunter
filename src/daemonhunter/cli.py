import argparse
import getpass
import sqlite3
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url

from daemonhunter.auth import hash_password
from daemonhunter.config import DATABASE_URL
from daemonhunter.database import SessionFactory, engine
from daemonhunter.models import User


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

    with SessionFactory() as session:
        statement = select(User).where(User.role == "owner")
        owner = session.scalar(statement)

        if owner is None:
            raise SystemExit("No owner account exists.")

        owner.password_hash = hash_password(password)
        owner.session_secret = token_urlsafe(32)
        owner.active = True
        owner.must_have_password = False

        session.commit()

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
            handler=lambda args: factory_reset(args.no_backup),
            )

    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
