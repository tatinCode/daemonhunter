"""Account UI checks reuse the existing temporary browser/server fixtures."""

import pytest
from sqlalchemy import select

playwright = pytest.importorskip("playwright.sync_api")

from test_dashboard_ui import PASSWORD, browser, create_owner, ui
from daemonhunter.models import User


def fill_password(page, current, new, confirm=None):
    page.locator("#account-current-password").fill(current)
    page.locator("#account-new-password").fill(new)
    page.locator("#account-confirm-password").fill(confirm if confirm is not None else new)
    page.locator('#account-password-form button[type="submit"]').click()


def test_guest_account_login_opens_profile(ui, browser):
    page, context, root = ui
    owner = browser.new_context()
    try:
        create_owner(owner, root)
        response = page.goto(root + "/account")
        assert response.status == 401
        playwright.expect(page.locator("#account-access")).to_be_visible()
        page.locator("#account-login").click()
        page.locator("#auth-username").fill("owner")
        page.locator("#auth-password").fill(PASSWORD)
        page.locator("#auth-submit").click()
        playwright.expect(page.locator("#account-content")).to_be_visible()
        playwright.expect(page.locator("#account-access")).to_be_hidden()
        playwright.expect(page.locator("#profile-username")).to_have_text("owner")
        playwright.expect(page.locator("#account-nav-link")).to_be_visible()
    finally:
        owner.close()


def test_account_password_errors_and_other_session_revocation(ui, browser):
    page, context, root = ui
    create_owner(context, root)
    other = browser.new_context()
    try:
        assert other.request.post(root + "/api/v1/auth/login", data={"username": "owner", "password": PASSWORD}).status == 200
        page.goto(root + "/account")
        playwright.expect(page.locator("#profile-username")).to_have_text("owner")
        fill_password(page, PASSWORD, "replacement secure password", "different secure password")
        playwright.expect(page.locator("#account-password-form .form-error")).to_contain_text("do not match")
        fill_password(page, "incorrect password", "replacement secure password")
        playwright.expect(page.locator("#account-password-form .form-error")).to_contain_text("Current password is incorrect")
        fill_password(page, PASSWORD, PASSWORD)
        playwright.expect(page.locator("#account-password-form .form-error")).to_contain_text("different from current password")
        fill_password(page, PASSWORD, "replacement secure password")
        playwright.expect(page.locator("#action-message-text")).to_contain_text("Password changed")
        for field in ("account-current-password", "account-new-password", "account-confirm-password"):
            playwright.expect(page.locator(f"#{field}")).to_have_value("")
        assert context.request.get(root + "/api/v1/auth/me").status == 200
        assert other.request.get(root + "/api/v1/auth/me").status == 401
        assert other.request.post(root + "/api/v1/auth/login", data={"username": "owner", "password": "replacement secure password"}).status == 200
    finally:
        other.close()


def test_owner_manages_admins_and_temporary_password_flow(ui, browser):
    page, context, root = ui
    create_owner(context, root)
    page.goto(root + "/users")
    playwright.expect(page.locator("#user-rows tr")).to_have_count(1)
    playwright.expect(page.locator('[data-user-id="1"] [data-user-action]')).to_have_count(0)
    page.locator("#add-admin-button").click()
    page.locator("#admin-username").fill("operator")
    page.locator("#admin-password").fill("temporary secure password")
    page.locator("#admin-confirm-password").fill("mismatched secure password")
    page.locator("#user-submit").click()
    playwright.expect(page.locator("#user-form .form-error")).to_contain_text("do not match")
    page.locator("#admin-confirm-password").fill("temporary secure password")
    page.locator("#user-submit").click()
    playwright.expect(page.locator("#user-rows tr")).to_have_count(2)
    playwright.expect(page.locator('tr[data-user-id="2"]')).to_contain_text("Change required")
    page.locator('[data-user-action="edit"][data-user-id="2"]').click()
    page.locator("#admin-username").fill("owner")
    page.locator("#user-submit").click()
    playwright.expect(page.locator("#user-form .form-error")).to_contain_text("already exists")
    page.locator("#admin-username").fill("operations")
    page.locator("#user-submit").click()
    playwright.expect(page.locator('tr[data-user-id="2"] th')).to_have_text("operations")

    admin = browser.new_context(viewport={"width": 375, "height": 900})
    try:
        assert admin.request.post(root + "/api/v1/auth/login", data={"username": "operations", "password": "temporary secure password"}).status == 200
        assert admin.request.get(root + "/api/v1/admin/devices").status == 403
        admin_page = admin.new_page()
        admin_page.goto(root + "/account")
        playwright.expect(admin_page.locator("#account-password-required")).to_be_visible()
        fill_password(admin_page, "temporary secure password", "replacement secure password")
        playwright.expect(admin_page.locator("#account-password-required")).to_be_hidden()
        assert admin.request.get(root + "/api/v1/admin/devices").status == 200
        playwright.expect(admin_page.locator("#users-nav-link")).to_be_hidden()
        admin_page.goto(root + "/users")
        playwright.expect(admin_page.locator("#users-access")).to_be_visible()
        playwright.expect(admin_page.locator("#users-content")).to_be_hidden()
        assert admin.request.get(root + "/api/v1/admin/users").status == 403

        page.locator('[data-user-action="active"][data-user-id="2"]').click()
        playwright.expect(page.locator('tr[data-user-id="2"]')).to_contain_text("Disabled")
        assert admin.request.get(root + "/api/v1/auth/me").status == 401
        page.locator('[data-user-action="active"][data-user-id="2"]').click()
        playwright.expect(page.locator('tr[data-user-id="2"]')).to_contain_text("Active")
        assert admin.request.post(root + "/api/v1/auth/login", data={"username": "operations", "password": "replacement secure password"}).status == 200
        page.locator('[data-user-action="reset"][data-user-id="2"]').click()
        page.locator("#admin-password").fill("another temporary password")
        page.locator("#admin-confirm-password").fill("another temporary password")
        page.locator("#user-submit").click()
        playwright.expect(page.locator('tr[data-user-id="2"]')).to_contain_text("Change required")
        assert admin.request.get(root + "/api/v1/auth/me").status == 401
        assert admin.request.post(root + "/api/v1/auth/login", data={"username": "operations", "password": "another temporary password"}).json()["must_change_password"] is True

        page.locator('[data-user-action="delete"][data-user-id="2"]').click()
        page.locator('[data-close="user-dialog"]').first.click()
        playwright.expect(page.locator("#user-rows tr")).to_have_count(2)
        page.locator('[data-user-action="delete"][data-user-id="2"]').click()
        page.locator("#user-submit").click()
        playwright.expect(page.locator("#user-rows tr")).to_have_count(1)
        assert admin.request.get(root + "/api/v1/auth/me").status == 401
    finally:
        admin.close()


@pytest.mark.parametrize("loss", ["revoked", "demoted"])
def test_user_page_permission_loss_clears_rows_closes_dialog_and_preserves_layout(ui, test_session_factory, loss):
    page, context, root = ui
    create_owner(context, root)
    assert context.request.post(root + "/api/v1/admin/users", data={"username": "operator", "temporary_password": "temporary secure password"}).status == 201
    page.goto(root + "/users")
    playwright.expect(page.locator("#user-rows tr")).to_have_count(2)
    for width in (375, 320):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for button in page.locator('[data-user-id="2"] [data-user-action]').all():
            box = button.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
    page.locator('[data-user-action="edit"][data-user-id="2"]').click()
    page.wait_for_timeout(5500)
    page.keyboard.press("Escape")
    playwright.expect(page.locator('[data-user-action="edit"][data-user-id="2"]')).to_be_focused()
    page.locator('[data-user-action="reset"][data-user-id="2"]').click()
    page.locator("#admin-password").fill("typed but not submitted password")
    with test_session_factory.begin() as session:
        owner = session.scalar(select(User).where(User.role == "owner"))
        if loss == "revoked":
            owner.session_secret = "revoked"
        else:
            owner.role = "admin"
            session.flush()
            session.get(User, 2).role = "owner"
    playwright.expect(page.locator("#users-access")).to_be_visible(timeout=15000)
    playwright.expect(page.locator("#user-dialog")).to_be_hidden()
    playwright.expect(page.locator("#user-rows tr")).to_have_count(0)
    playwright.expect(page.locator("#admin-password")).to_have_value("")
    playwright.expect(page.locator("#users-nav-link")).to_be_hidden()
