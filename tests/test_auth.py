from fastapi.testclient import TestClient

OWNER_CREDENTIALS = {
        "username": "owner",
        "password": "correct horse battery staple",
        }


def test_reports_setup_status(
        api_client: TestClient,
        ) -> None:
    before_setup = api_client.get(
            "/api/v1/auth/setup-status",
            )

    assert before_setup.status_code == 200
    assert before_setup.json() == {
            "setup_required": True,
            }
