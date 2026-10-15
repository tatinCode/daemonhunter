import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from daemonhunter.models import Device, DeviceStatusEvent, User


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_state = False
        self.state_text = ""
        self.assets: list[str] = []
        self.favicon: str | None = None
        self.elements_by_id: dict[str, dict] = {}
        self.button_text: dict[str, str] = {}
        self.active_button: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.elements_by_id[values["id"]] = values
        if tag == "button":
            self.active_button = values.get("id")
            if self.active_button:
                self.button_text[self.active_button] = ""
        if tag == "script" and values.get("id") == "dashboard-state":
            self.in_state = True
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet":
            self.assets.append(values["href"])
        if tag == "link" and values.get("rel") == "icon":
            self.favicon = values["href"]

    def handle_data(self, data: str) -> None:
        if self.active_button:
            self.button_text[self.active_button] += data
        if self.in_state:
            self.state_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self.active_button = None
        if tag == "script":
            self.in_state = False


def get_state(client: TestClient, path: str) -> tuple[Response, dict]:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    if path == "/":
        assert response.headers["content-type"].startswith("text/html")
        parser = DashboardParser()
        parser.feed(response.text)
        return response, json.loads(parser.state_text)
    return response, response.json()


def seed_devices(factory: sessionmaker[Session]) -> tuple[int, int]:
    with factory.begin() as session:
        public = Device(name="Public Pi", host="public.local", status="online", guest_visible=True)
        private = Device(name="Private NAS", host="private.local", status="offline", consecutive_failures=4)
        unknown = Device(name="New Pi", host="new.local", guest_visible=True)
        session.add_all([public, private, unknown])
        session.flush()
        session.add_all([
                DeviceStatusEvent(device_id=public.id, previous_status="unknown", new_status="online"),
                DeviceStatusEvent(device_id=private.id, previous_status="online", new_status="offline"),
                ])
    return public.id, private.id


@pytest.mark.parametrize("path", ["/", "/dashboard/state"])
def test_guest_dashboard_never_exposes_private_devices_or_history(
        api_client: TestClient,
        test_session_factory: sessionmaker[Session],
        path: str,
        ) -> None:
    seed_devices(test_session_factory)
    response, data = get_state(api_client, path)

    assert {device["name"] for device in data["devices"]} == {"Public Pi", "New Pi"}
    assert data["counts"] == {"total": 2, "online": 1, "offline": 0, "unknown": 1, "attention": 1}
    assert data["events"] == []
    assert data["selected_events"] == []
    assert data["can_manage"] is False
    assert data["user"] is None
    assert "Private NAS" not in response.text
    assert "private.local" not in response.text
    for device in data["devices"]:
        assert set(device) == {"id", "name", "host", "status"}


@pytest.mark.parametrize("path", ["/", "/dashboard/state"])
def test_admin_dashboard_shows_real_counts_activity_and_selected_history(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        path: str,
        ) -> None:
    seed_devices(test_session_factory)
    _, data = get_state(admin_client, path)

    assert data["counts"] == {"total": 3, "online": 1, "offline": 1, "unknown": 1, "attention": 2}
    assert data["can_manage"] is True
    assert data["user"] == {"username": "owner", "role": "owner", "must_change_password": False}
    assert data["setup_required"] is False
    assert [event["name"] for event in data["events"]] == ["Private NAS", "Public Pi"]
    assert all(event["occurred_at"].endswith("+00:00") for event in data["events"])
    assert "password_hash" not in json.dumps(data)
    assert "session_secret" not in json.dumps(data)


def test_dashboard_selected_history_is_scoped_and_bounded(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    public_id, private_id = seed_devices(test_session_factory)
    with test_session_factory.begin() as session:
        session.add_all([
                DeviceStatusEvent(
                    device_id=public_id,
                    previous_status="online" if index % 2 == 0 else "offline",
                    new_status="offline" if index % 2 == 0 else "online",
                    occurred_at=datetime(2026, 10, 13, 12, index, tzinfo=timezone.utc),
                    )
                for index in range(55)
                ])

    _, data = get_state(admin_client, f"/dashboard/state?selected_id={public_id}")
    assert data["selected_id"] == public_id
    assert len(data["selected_events"]) == 50
    assert len(data["events"]) == 50
    ids = [event["id"] for event in data["selected_events"]]
    assert ids == sorted(ids, reverse=True)

    _, other = get_state(admin_client, f"/dashboard/state?selected_id={private_id}")
    assert len(other["selected_events"]) == 1
    assert other["selected_events"][0]["new_status"] == "offline"


def test_guest_cannot_request_hidden_device_history(
        api_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    _, private_id = seed_devices(test_session_factory)
    _, data = get_state(api_client, f"/dashboard/state?selected_id={private_id}")
    assert data["selected_id"] != private_id
    assert data["selected_events"] == []
    assert "private.local" not in json.dumps(data)


@pytest.mark.parametrize("path", ["/", "/dashboard/state"])
def test_revoked_session_falls_back_to_guest_dashboard(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        path: str,
        ) -> None:
    seed_devices(test_session_factory)
    with test_session_factory.begin() as session:
        owner = session.scalar(select(User).where(User.role == "owner"))
        owner.session_secret = "revoked-secret"

    _, data = get_state(admin_client, path)
    assert data["can_manage"] is False
    assert data["user"] is None
    assert data["counts"]["total"] == 2
    assert data["events"] == []


@pytest.mark.parametrize("path", ["/", "/dashboard/state"])
def test_password_change_required_does_not_grant_dashboard_admin_data(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        path: str,
        ) -> None:
    seed_devices(test_session_factory)
    with test_session_factory.begin() as session:
        session.scalar(select(User).where(User.role == "owner")).must_change_password = True

    _, data = get_state(admin_client, path)
    assert data["can_manage"] is False
    assert data["user"]["must_change_password"] is True
    assert data["counts"]["total"] == 2
    assert data["events"] == []


def test_dashboard_refresh_reflects_creation_visibility_and_deletion(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    created = admin_client.post("/api/v1/admin/devices", json={"name": "New NAS", "host": "nas.local"})
    assert created.status_code == 201
    device_id = created.json()["id"]
    _, data = get_state(admin_client, "/dashboard/state")
    assert data["devices"][0]["status"] == "unknown"
    assert data["devices"][0]["guest_visible"] is False

    with test_session_factory.begin() as session:
        session.get(Device, device_id).status = "online"
    _, refreshed = get_state(admin_client, "/dashboard/state")
    assert refreshed["counts"]["online"] == 1

    admin_client.post("/api/v1/auth/logout")
    _, guest = get_state(admin_client, "/dashboard/state")
    assert guest["devices"] == []

    with test_session_factory.begin() as session:
        session.get(Device, device_id).guest_visible = True
    _, shared = get_state(admin_client, "/dashboard/state")
    assert shared["counts"]["total"] == 1

    with test_session_factory.begin() as session:
        session.delete(session.get(Device, device_id))
    _, removed = get_state(admin_client, "/dashboard/state")
    assert removed["counts"]["total"] == 0
    assert removed["selected_id"] is None


def test_dashboard_escapes_html_and_embedded_json(
        api_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    name = '</script><script>alert("xss")</script>'
    host = '<img src=x onerror="alert(1)">'
    with test_session_factory.begin() as session:
        session.add(Device(name=name, host=host, guest_visible=True))
    response, data = get_state(api_client, "/")
    assert name not in response.text
    assert host not in response.text
    assert data["devices"][0]["name"] == name
    assert data["devices"][0]["host"] == host
    assert "&lt;img" in response.text
    assert "\\u003c/script\\u003e" in response.text


def test_dashboard_assets_and_templates_work_outside_repository(
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        ) -> None:
    monkeypatch.chdir(tmp_path)
    response, data = get_state(api_client, "/")
    assert data["setup_required"] is True
    assert data["counts"]["total"] == 0
    assert "No devices to display" in response.text
    parser = DashboardParser()
    parser.feed(response.text)
    assert len(parser.assets) == 2
    assert parser.favicon is not None
    favicon = api_client.get(parser.favicon)
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in favicon.text
    for url in parser.assets:
        assert url.startswith("http://testserver/static/")
        asset = api_client.get(url)
        assert asset.status_code == 200
        assert asset.content
        assert "text/html" not in asset.headers["content-type"]


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_dashboard_rejects_invalid_selection(api_client: TestClient, value: str) -> None:
    response = api_client.get(f"/dashboard/state?selected_id={value}")
    assert response.status_code == 422


@pytest.mark.parametrize(
        "account_state, expected_label, identity_visible",
        [
            ("fresh", "Set up owner", False),
            ("signed_out", "Log in", False),
            ("password_required", "Change password", True),
            ("ready", "", True),
            ],
        )
def test_dashboard_account_actions_and_add_device_visibility(
        request: pytest.FixtureRequest,
        api_client: TestClient,
        test_session_factory: sessionmaker[Session],
        account_state: str,
        expected_label: str,
        identity_visible: bool,
        ) -> None:
    if account_state != "fresh":
        request.getfixturevalue("admin_client")
    if account_state == "signed_out":
        assert api_client.post("/api/v1/auth/logout").status_code == 204
    elif account_state == "password_required":
        with test_session_factory.begin() as session:
            session.scalar(select(User).where(User.role == "owner")).must_change_password = True

    response = api_client.get("/")
    assert response.status_code == 200
    parser = DashboardParser()
    parser.feed(response.text)
    assert "hidden" not in parser.elements_by_id["add-device-button"]
    assert parser.button_text["add-device-button"] == "Add device"
    assert ("hidden" not in parser.elements_by_id["account-identity"]) is identity_visible
    if account_state == "ready":
        assert "hidden" in parser.elements_by_id["auth-button"]
    else:
        assert "hidden" not in parser.elements_by_id["auth-button"]
        assert parser.button_text["auth-button"] == expected_label

    if account_state in {"fresh", "signed_out", "password_required"}:
        response = api_client.post(
                "/api/v1/admin/devices",
                json={"name": "Unauthorized Pi", "host": "private.local"},
                )
        assert response.status_code == (403 if account_state == "password_required" else 401)


@pytest.mark.parametrize("path, title", [("/devices", "Devices"), ("/activity", "Activity")])
def test_dedicated_pages_have_navigation_and_preserve_guest_privacy(
        api_client: TestClient,
        test_session_factory: sessionmaker[Session],
        path: str,
        title: str,
        ) -> None:
    _, private_id = seed_devices(test_session_factory)
    response = api_client.get(path, params={"selected_id": private_id})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f"<h1>{title}</h1>" in response.text
    assert 'href="http://testserver/devices"' in response.text
    assert 'href="http://testserver/activity"' in response.text
    assert "Private NAS" not in response.text
    assert "private.local" not in response.text
    parser = DashboardParser()
    parser.feed(response.text)
    assert json.loads(parser.state_text)["can_manage"] is False
    if path == "/devices":
        assert "Read-only view of shared devices" in response.text
    else:
        assert "Status activity is available to admins" in response.text
        assert "hidden" in parser.elements_by_id["activity-content"]


def test_devices_deep_link_selects_allowed_device(
        admin_client: TestClient,
        test_session_factory: sessionmaker[Session],
        ) -> None:
    _, private_id = seed_devices(test_session_factory)
    response = admin_client.get("/devices", params={"selected_id": private_id})
    assert response.status_code == 200
    parser = DashboardParser()
    parser.feed(response.text)
    data = json.loads(parser.state_text)
    assert data["selected_id"] == private_id
    assert data["selected_events"][0]["new_status"] == "offline"
    assert "Guest visibility" in response.text
    assert "Delete device?" in response.text
