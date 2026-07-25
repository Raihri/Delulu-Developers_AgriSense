from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


def test_judge_demo_page_is_served_without_browser_supabase_credentials() -> None:
    response = TestClient(app).get("/demo", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:3000/"
