"""Opt-in checks: uv run --group browser pytest tests/browser --run-browser -q."""

import json
import os
from pathlib import Path
import shutil
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

playwright = pytest.importorskip("playwright.sync_api")
import uvicorn

from daemonhunter.auth import get_setup_token
from daemonhunter.database import get_session
from daemonhunter.main import create_app
from daemonhunter.models import Device, DeviceStatusEvent, User
from daemonhunter.rate_limit import login_limiter, setup_limiter


SETUP_TOKEN = "dashboard-browser-test-token-1234567890"
PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="module")
def browser(request):
    if not request.config.getoption("--run-browser"):
        pytest.skip("Use --run-browser to enable Chromium dashboard checks")
    with playwright.sync_playwright() as runner:
        executable = os.environ.get("DAEMONHUNTER_TEST_BROWSER") or shutil.which("chromium") or shutil.which("chromium-browser")
        if not executable and not Path(runner.chromium.executable_path).is_file():
            if os.environ.get("CI"):
                pytest.fail("Chromium is required for the browser CI job")
            pytest.skip("Install Chromium with: uv run --group browser playwright install chromium")
        instance = runner.chromium.launch(
                headless=True,
                **({"executable_path": executable} if executable else {}),
                )
        yield instance
        instance.close()


@pytest.fixture
def ui(browser, test_session_factory):
    app = create_app()

    def sessions():
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_setup_token] = lambda: SETUP_TOKEN
    login_limiter.reset()
    setup_limiter.reset()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    root = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, timezone_id="UTC")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started, "Temporary test server did not start"
        yield page, context, root
        assert not errors, errors
    finally:
        context.close()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        login_limiter.reset()
        setup_limiter.reset()


def create_owner(context, root):
    response = context.request.post(root + "/api/v1/auth/setup", data={
            "username": "owner", "password": PASSWORD, "setup_token": SETUP_TOKEN,
            })
    assert response.status == 201


def seed_devices(factory, long_values=False):
    with factory.begin() as session:
        session.add_all([
                Device(name="Alpha Pi" if not long_values else "A" * 100,
                       host="alpha.local" if not long_values else "host-" + "x" * 240 + ".local",
                       status="online", guest_visible=True),
                Device(name="Beta NAS", host="beta.local", status="offline", guest_visible=True),
                Device(name="Gamma Router", host="gamma.local"),
                ])


def test_device_filters_reload_navigation_and_back(ui, test_session_factory):
    page, context, root = ui
    seed_devices(test_session_factory)
    create_owner(context, root)
    page.goto(root + "/devices")
    page.locator("#device-search").fill("Alpha")
    page.locator('[data-filter="online"]').click()
    page.locator("#sort-name").click()
    assert "q=Alpha" in page.url and "status=online" in page.url and "sort=name_desc" in page.url
    page.reload()
    playwright.expect(page.locator("#device-search")).to_have_value("Alpha")
    playwright.expect(page.locator('[data-filter="online"]')).to_have_attribute("aria-pressed", "true")
    playwright.expect(page.locator("#device-name-heading")).to_have_attribute("aria-sort", "descending")
    playwright.expect(page.locator("#device-rows tr")).to_have_count(1)
    page.locator('.navigation a', has_text="Activity").click()
    playwright.expect(page.locator("h1")).to_have_text("Activity")
    page.go_back()
    playwright.expect(page.locator("#device-search")).to_have_value("Alpha")
    playwright.expect(page.locator("#device-rows tr")).to_have_count(1)
    page.locator('[data-filter="all"]').click()
    playwright.expect(page.locator('[data-filter="all"]')).to_have_attribute("aria-pressed", "true")
    page.go_back()
    playwright.expect(page.locator('[data-filter="online"]')).to_have_attribute("aria-pressed", "true")
    page.go_forward()
    playwright.expect(page.locator('[data-filter="all"]')).to_have_attribute("aria-pressed", "true")


def test_activity_bookmark_pagination_and_steady_refresh(ui, test_session_factory):
    page, context, root = ui
    seed_devices(test_session_factory)
    with test_session_factory.begin() as session:
        session.add_all([
                DeviceStatusEvent(device_id=1, previous_status="offline", new_status="online",
                                  occurred_at=datetime(2026, 10, 13, 12, tzinfo=timezone.utc) + timedelta(minutes=index))
                for index in range(60)
                ])
    create_owner(context, root)
    page.goto(root + "/activity?device_id=1&new_status=online&limit=25")
    playwright.expect(page.locator("#history-rows tr")).to_have_count(25)
    page.locator("#history-next").click()
    playwright.expect(page.locator("#history-page")).to_have_text("Page 2 of 3")
    bookmark = page.url
    rows = page.locator("#history-rows").inner_text()
    assert "page=2" in bookmark and "snapshot_id=" in bookmark
    page.reload()
    playwright.expect(page.locator("#history-page")).to_have_text("Page 2 of 3")
    assert page.locator("#history-rows").inner_text() == rows
    playwright.expect(page.locator("#activity-device")).to_have_value("1")
    playwright.expect(page.locator("#activity-status")).to_have_value("online")
    page.locator('.navigation a', has_text="Devices").click()
    page.go_back()
    playwright.expect(page.locator("#history-page")).to_have_text("Page 2 of 3")
    assert page.locator("#history-rows").inner_text() == rows

    page.goto(root + "/activity?device_id=1&start=2026-10-13T12%3A05%3A00Z&end=2026-10-13T12%3A10%3A00Z")
    playwright.expect(page.locator("#history-count")).to_have_text("6 matching transitions")
    playwright.expect(page.locator("#activity-start")).to_have_value("2026-10-13T12:05")
    playwright.expect(page.locator("#activity-end")).to_have_value("2026-10-13T12:10")
    table_y = page.locator("#history-results").bounding_box()["y"]
    pending = []
    payload = context.request.get(root + "/api/v1/admin/status-events?device_id=1&start=2026-10-13T12:05:00Z&end=2026-10-13T12:10:00Z").json()
    page.route("**/api/v1/admin/status-events*", lambda route: pending.append(route))
    page.locator("#activity-refresh").click()
    playwright.expect(page.locator("#activity-refreshing")).to_be_visible()
    playwright.expect(page.locator("#activity-loading")).to_be_hidden()
    assert abs(page.locator("#history-results").bounding_box()["y"] - table_y) < 1
    assert len(pending) == 1
    pending[0].fulfill(status=200, content_type="application/json", body=json.dumps(payload))
    page.unroute("**/api/v1/admin/status-events*")
    playwright.expect(page.locator("#activity-refreshing")).to_be_hidden()
    assert abs(page.locator("#history-results").bounding_box()["y"] - table_y) < 1


def test_mobile_cards_actions_long_values_and_keyboard_focus(ui, test_session_factory):
    page, context, root = ui
    seed_devices(test_session_factory, long_values=True)
    create_owner(context, root)
    page.goto(root + "/devices")
    for width in (375, 320):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for selector in ('[data-edit="1"]', '[data-delete="1"]', '[data-visibility="1"]'):
            box = page.locator(selector).bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
        row_width = page.locator('[data-device-id="1"]').bounding_box()["width"]
        heading_width = page.locator('[data-device-id="1"] th').bounding_box()["width"]
        assert heading_width > row_width * .8
        playwright.expect(page.locator("#sort-devices-mobile")).to_be_visible()
    page.locator('[data-edit="1"]').focus()
    page.wait_for_timeout(5500)
    playwright.expect(page.locator('[data-edit="1"]')).to_be_focused()
    page.keyboard.press("Enter")
    playwright.expect(page.locator("#device-dialog")).to_be_visible()
    page.wait_for_timeout(5500)
    page.keyboard.press("Escape")
    playwright.expect(page.locator('[data-edit="1"]')).to_be_focused()
    page.locator('[data-delete="1"]').click()
    playwright.expect(page.locator("#delete-dialog")).to_be_visible()
    page.locator('[data-close="delete-dialog"]').first.click()
    playwright.expect(page.locator('[data-delete="1"]')).to_be_focused()


def test_notification_types_dismissal_and_required_password_info(ui, test_session_factory):
    page, context, root = ui
    seed_devices(test_session_factory)
    create_owner(context, root)
    page.goto(root + "/devices")
    page.route("**/api/v1/admin/devices/1", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"Service unavailable"}'))
    page.locator('[data-visibility="1"]').click()
    playwright.expect(page.locator("#action-message")).to_have_class("notice notification error")
    playwright.expect(page.locator("#action-message-text")).to_have_attribute("role", "alert")
    playwright.expect(page.locator("#action-message-text")).to_contain_text("Error: Could not change visibility")
    page.locator("#dismiss-notification").click()
    playwright.expect(page.locator("#action-message")).to_be_hidden()
    playwright.expect(page.locator("#main")).to_be_focused()
    page.unroute("**/api/v1/admin/devices/1")
    page.locator('[data-visibility="1"]').click()
    playwright.expect(page.locator("#action-message")).to_have_class("notice notification success")
    playwright.expect(page.locator("#action-message-text")).to_have_attribute("aria-live", "polite")

    with test_session_factory.begin() as session:
        session.scalar(select(User).where(User.role == "owner")).must_change_password = True
    context.clear_cookies()
    page.reload()
    page.locator("#auth-button").click()
    page.locator("#auth-username").fill("owner")
    page.locator("#auth-password").fill(PASSWORD)
    page.locator("#auth-submit").click()
    playwright.expect(page.locator("#auth-dialog-title")).to_have_text("Change password")
    playwright.expect(page.locator("#action-message")).to_have_class("notice notification info")
    playwright.expect(page.locator("#action-message-text")).to_contain_text("Information:")


def test_empty_state_account_and_clear_filter_actions(ui, test_session_factory):
    page, context, root = ui
    page.goto(root + "/devices")
    playwright.expect(page.locator("#devices-empty-action")).to_have_text("Set up owner")
    page.locator("#devices-empty-action").click()
    playwright.expect(page.locator("#auth-dialog-title")).to_have_text("Set up owner")
    page.keyboard.press("Escape")
    playwright.expect(page.locator("#devices-empty-action")).to_be_focused()
    create_owner(context, root)
    page.reload()
    playwright.expect(page.locator("#devices-empty-action")).to_have_text("Add device")
    page.locator("#devices-empty-action").click()
    playwright.expect(page.locator("#device-dialog")).to_be_visible()
    page.keyboard.press("Escape")
    seed_devices(test_session_factory)
    page.reload()
    page.locator("#device-search").fill("no matching devices")
    playwright.expect(page.locator("#clear-device-filters")).to_be_visible()
    page.locator("#clear-device-filters").click()
    playwright.expect(page.locator("#device-rows tr")).to_have_count(3)
    page.locator('.navigation a', has_text="Activity").click()
    playwright.expect(page.locator("#history-empty h3")).to_have_text("No transitions recorded yet")
    page.locator("#activity-search").fill("no matches")
    page.locator('#activity-filters button[type="submit"]').click()
    playwright.expect(page.locator("#history-clear-filters")).to_be_visible()
    page.locator("#history-clear-filters").click()
    playwright.expect(page.locator("#history-clear-filters")).to_be_hidden()
