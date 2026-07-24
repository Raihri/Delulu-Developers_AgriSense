from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app, require_supabase
from kb.build import seed_supabase
from state.store import SupabaseStateStore
from tests.fakes import FakeSupabaseClient


def _forecast(days: int) -> dict[str, object]:
    return {
        "source_id": "open_meteo",
        "timezone": "Asia/Dhaka",
        "daily_units": {"precipitation_sum": "mm", "et0_fao_evapotranspiration": "mm"},
        "daily": {
            "time": [f"2026-12-{d:02d}" for d in range(1, days + 1)],
            "temperature_2m_min": [12.0] * days,
            "temperature_2m_max": [29.0] * days,
            "precipitation_sum": [0.0] * days,
            "et0_fao_evapotranspiration": [4.0] * days,
        },
    }


def _client(monkeypatch) -> tuple[TestClient, FakeSupabaseClient]:
    monkeypatch.setattr("app.fetch_forecast", lambda _lat, _lon, *, days: _forecast(days))
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    return TestClient(app), fake


def _seed_intake(fake: FakeSupabaseClient, session_id: str, recognized: dict) -> None:
    SupabaseStateStore(fake).save_session(
        session_id,
        {"schema_version": "intake_context_v1", "recognized": recognized},
    )


def test_completed_conversation_produces_ranked_costed_dated_traced_plan(monkeypatch):
    client, fake = _client(monkeypatch)
    try:
        _seed_intake(
            fake,
            "intake-complete",
            {
                "soil_class": "loam",
                "drainage_condition": "well_drained",
                "water_availability": "irrigation_available",
                "budget_bdt": 20000,
                "target_season": "rabi",
                "area_acres": 1,
                "sowing_date": "2026-11-15",
            },
        )
        response = client.post(
            "/plan/from-conversation",
            json={
                "session_id": "intake-complete",
                "lat": 24.89539917,
                "lon": 89.35605547,
                "starting_depletion_mm": 40.0,
                "irrigation_mm_per_day": 0.0,
                "soil_test_class": "medium",
            },
        )
        assert response.status_code == 200
        body = response.json()
        # One path: the profile came from the conversation, not the plan call.
        assert body["from_conversation_session"] == "intake-complete"
        assert body["profile_used"]["target_season"] == "rabi"
        assert body["profile_used"]["budget_bdt"] == 20000
        # Ranked (cap 3), dated chosen plan (cap 4), grounded (cap 7), traced (cap 8).
        assert body["status"] == "ranked"
        assert len(body["ranked"]) == 3
        assert {"land_preparation", "harvest"} <= {
            e["operation"] for e in body["chosen_plan"]["events"]
        }
        assert body["chosen_plan"]["grounding"]["status"] == "grounded"
        assert body["trace_ids"]
        traces = client.get(
            f"/plan/preview/{body['session_id']}/traces"
        ).json()["traces"]
        assert "ranking.rank_candidates" in {t["tool"] for t in traces}
    finally:
        app.dependency_overrides.clear()


def test_incomplete_conversation_fails_closed_with_missing_fields(monkeypatch):
    client, fake = _client(monkeypatch)
    try:
        _seed_intake(
            fake,
            "intake-partial",
            {"soil_class": "loam", "area_acres": 1},  # budget/water/season missing
        )
        response = client.post(
            "/plan/from-conversation",
            json={"session_id": "intake-partial", "lat": 24.9, "lon": 89.3},
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "budget" in detail["missing"]
        assert "target season" in detail["missing"]
    finally:
        app.dependency_overrides.clear()


def test_non_intake_session_is_rejected(monkeypatch):
    client, fake = _client(monkeypatch)
    try:
        SupabaseStateStore(fake).save_session(
            "not-intake", {"schema_version": "plan_rank_v1"}
        )
        response = client.post(
            "/plan/from-conversation",
            json={"session_id": "not-intake", "lat": 24.9, "lon": 89.3},
        )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
