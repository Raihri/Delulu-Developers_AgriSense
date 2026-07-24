from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


def test_judge_demo_page_is_served_without_browser_supabase_credentials() -> None:
    response = TestClient(app).get("/demo")

    assert response.status_code == 200
    assert "AgriSense AI" in response.text
    assert "Bogura demo input" in response.text
    assert "requestPreview('/plan/preview'" in response.text
    assert "SUPABASE_SECRET_KEY" not in response.text
    assert "SUPABASE_DB_URL" not in response.text
