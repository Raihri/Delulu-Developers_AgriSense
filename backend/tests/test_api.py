from __future__ import annotations

from fastapi.testclient import TestClient

from app import app, require_supabase
from kb.build import seed_supabase
from tests.fakes import FakeSupabaseClient


def test_health_and_assumption_gate() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    try:
        client = TestClient(app)
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["quality_status"] == "passed"
        assert health.json()["storage_backend"] == "supabase_postgres_pgvector"

        search = client.get(
            "/kb/search",
            params={"q": "maize fertilizer nitrogen timing", "crop": "maize", "limit": 1},
        )
        assert search.status_code == 200
        assert search.json()["results"][0]["source_id"] == "barc_frg_2024"
        assert search.json()["results"][0]["source_locator"] == "PDF page 91"

        blocked = client.post(
            "/financials",
            json={"crop_id": "maize", "area_acres": 1, "allow_assumptions": False},
        )
        assert blocked.status_code == 422

        allowed = client.post(
            "/financials",
            json={"crop_id": "maize", "area_acres": 1, "allow_assumptions": True},
        )
        assert allowed.status_code == 200
        assert allowed.json()["assumption_gate"] == "explicitly_accepted"
    finally:
        app.dependency_overrides.clear()


def test_paddy_water_endpoint_fails_closed() -> None:
    client = TestClient(app)
    response = client.post(
        "/water/balance",
        json={
            "crop_id": "boro_rice",
            "taw_mm": 100,
            "depletion_fraction": 0.5,
            "days": [{"etc_mm": 5}],
        },
    )
    assert response.status_code == 422
    assert "Paddy rice" in response.json()["detail"]


def test_geo_and_recommendation_contract_remains_transparent() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    try:
        client = TestClient(app)
        geo = client.post(
            "/geo/resolve", json={"lat": 24.89539917, "lon": 89.35605547}
        )
        assert geo.status_code == 200
        geo_body = geo.json()
        assert geo_body["admin"]["adm3"]["pcode"] == "BD50100020"
        assert geo_body["point_aez_resolved"] is False
        assert {row["aez_id"] for row in geo_body["aez_candidates"]} == {3, 25, 27}

        recommendations = client.post(
            "/recommendations",
            json={
                "soil_class": "loam",
                "drainage_condition": "well_drained",
                "area_acres": 1,
                "allow_assumptions": False,
            },
        )
        assert recommendations.status_code == 200
        body = recommendations.json()
        assert {row["crop_id"] for row in body["candidates"]} == {
            "boro_rice",
            "maize",
            "lentil",
            "wheat",
        }
        assert all(
            row["ranking_status"]
            == "not_ranked_until_all_limiting_factors_are_available"
            for row in body["candidates"]
        )
        boro = next(row for row in body["candidates"] if row["crop_id"] == "boro_rice")
        assert boro["soil_class"] == "unassessed"
        assert "not a fabricated ranking" in body["warning"]
    finally:
        app.dependency_overrides.clear()
