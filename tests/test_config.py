from pathlib import Path

from daemonhunter.config import (
        resolve_database_url,
        resolve_default_database_path,
        )


def test_resolves_xdg_database_path(tmp_path: Path) -> None:
    xdg_data_home = tmp_path / "xdg"

    database_path = resolve_default_database_path(
            str(xdg_data_home),
            tmp_path / "home",
            )

    assert database_path == (
            xdg_data_home
            / "daemonhunter"
            / "daemonhunter.db"
            )


def test_falls_back_to_home_data_directory(
        tmp_path: Path
        ) -> None:
    home_directory = tmp_path / "home"

    database_path = resolve_default_database_path(
            None,
            home_directory,
            )

    assert database_path == (
            home_directory
            / ".local"
            / "share"
            / "daemonhunter"
            / "daemonhunter.db"
            )


def test_falls_back_when_xdg_data_home_is_empty(
        tmp_path: Path,
        ) -> None:
    home_directory = tmp_path / "home"

    database_path = resolve_default_database_path(
            "",
            home_directory,
            )

    assert database_path == (
            home_directory
            / ".local"
            / "share"
            / "daemonhunter"
            / "daemonhunter.db"
            )


def test_rejects_relative_xdg_directory(
        tmp_path: Path
        ) -> None:
    home_directory = tmp_path / "home"

    database_path = resolve_default_database_path(
            "relative/data",
            home_directory,
            )

    assert database_path == (
            home_directory
            / ".local"
            / "share"
            / "daemonhunter"
            / "daemonhunter.db"
            )


def test_preserves_explicit_database_url(
        tmp_path: Path
        ) -> None:
    configured_url = "sqlite:///custom/daemonhunter.db"

    assert resolve_database_url(
            configured_url,
            tmp_path / "default.db",
            ) == configured_url


def test_builds_default_database_url(
        tmp_path: Path
        ) -> None:
    database_path = tmp_path / "daemonhunter.db"

    assert resolve_database_url(
            None,
            database_path,
            ) == f"sqlite:///{database_path}"
