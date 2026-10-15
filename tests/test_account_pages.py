from html.parser import HTMLParser
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.models import User


class AccountPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: dict[str, dict] = {}
        self.script_id: str | None = None
        self.scripts: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.elements[values["id"]] = values
        if tag == "script" and values.get("type") == "application/json":
            self.script_id = values["id"]
            self.scripts[self.script_id] = ""

    def handle_data(self, data: str) -> None:
        if self.script_id:
            self.scripts[self.script_id] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.script_id = None


@pytest.mark.parametrize("path", ["/account", "/users"])
def test_account_pages_require_login_and_do_not_cache(api_client: TestClient, path: str) -> None:
    response = api_client.get(path)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    parser = AccountPageParser()
    parser.feed(response.text)
    assert "hidden" in parser.elements["account-nav-link"]
    assert "hidden" in parser.elements["users-nav-link"]
    assert json.loads(parser.scripts["account-viewer"]) is None
    assert "hidden" not in parser.elements[f"{'account' if path == '/account' else 'users'}-access"]


@pytest.mark.parametrize("path", ["/account", "/users"])
def test_owner_can_access_account_and_users_without_exposing_secrets(
        admin_client: TestClient,
        path: str,
        ) -> None:
    response = admin_client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    parser = AccountPageParser()
    parser.feed(response.text)
    assert "hidden" not in parser.elements["account-nav-link"]
    assert "hidden" not in parser.elements["users-nav-link"]
    assert json.loads(parser.scripts["account-viewer"]) == {
            "username": "owner", "role": "owner", "must_change_password": False,
            }
    assert "password_hash" not in response.text
    assert "session_secret" not in response.text


def test_admin_has_own_account_but_not_owner_users_page(
        admin_client: TestClient,
        secondary_client: TestClient,
        ) -> None:
    response = admin_client.post("/api/v1/admin/users", json={
            "username": "operator", "temporary_password": "temporary secure password",
            })
    assert response.status_code == 201
    assert secondary_client.post("/api/v1/auth/login", json={
            "username": "operator", "password": "temporary secure password",
            }).status_code == 200

    account = secondary_client.get("/account")
    assert account.status_code == 200
    parser = AccountPageParser()
    parser.feed(account.text)
    assert "hidden" not in parser.elements["account-password-required"]
    assert "hidden" not in parser.elements["account-nav-link"]
    assert "hidden" in parser.elements["users-nav-link"]
    assert secondary_client.get("/users").status_code == 403

    assert secondary_client.post("/api/v1/auth/change-password", json={
            "current_password": "temporary secure password", "new_password": "replacement secure password",
            }).status_code == 200
    assert secondary_client.get("/account").status_code == 200
    users = secondary_client.get("/users")
    assert users.status_code == 403
    assert users.headers["cache-control"] == "no-store"
    parser = AccountPageParser()
    parser.feed(users.text)
    assert "hidden" in parser.elements["users-content"]
    assert "Owner access required" in users.text
    assert secondary_client.get("/api/v1/admin/users").status_code == 403


def test_owner_with_required_password_change_cannot_access_users(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    with test_session_factory.begin() as session:
        session.scalar(select(User).where(User.role == "owner")).must_change_password = True
    assert admin_client.get("/account").status_code == 200
    response = admin_client.get("/users")
    assert response.status_code == 403
    assert "Change your temporary password before continuing" in response.text


@pytest.mark.parametrize("path", ["/account", "/users"])
def test_revoked_session_cannot_access_account_pages(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        path: str,
        ) -> None:
    with test_session_factory.begin() as session:
        session.scalar(select(User).where(User.role == "owner")).session_secret = "revoked"
    response = admin_client.get(path)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_account_username_is_escaped_in_html_and_viewer_json(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    username = '</script><img src=x onerror="alert(1)">'
    with test_session_factory.begin() as session:
        session.scalar(select(User).where(User.role == "owner")).username = username
    response = admin_client.get("/account")
    assert response.status_code == 200
    assert username not in response.text
    assert "&lt;/script&gt;" in response.text
    parser = AccountPageParser()
    parser.feed(response.text)
    assert json.loads(parser.scripts["account-viewer"])["username"] == username
