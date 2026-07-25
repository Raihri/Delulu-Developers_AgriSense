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


def test_completed_conversation_waits_for_farmer_then_builds_selected_plan(monkeypatch):
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
        request = {
            "session_id": "intake-complete",
            "lat": 24.89539917,
            "lon": 89.35605547,
            "starting_depletion_mm": 40.0,
            "irrigation_mm_per_day": 0.0,
            "soil_test_class": "medium",
            "allow_assumptions": True,
        }
        ranked_response = client.post(
            "/plan/from-conversation",
            json=request,
        )
        assert ranked_response.status_code == 200
        ranked = ranked_response.json()
        assert ranked["status"] == "awaiting_farmer_crop_selection"
        assert ranked["recommended_crop_id"] == ranked["ranked"][0]["crop_id"]
        assert ranked["chosen_crop_id"] is None
        assert ranked["selection_source"] == "awaiting_farmer"
        assert ranked["chosen_plan"] is None

        response = client.post(
            "/plan/from-conversation",
            json={
                **request,
                "selected_crop_id": "lentil",
                "budget_bdt": 9_000,
                "financial_overrides": {
                    "lentil": {
                        "seed_cost_per_acre_bdt": 1_000,
                        "fertilizer_bundle_cost_per_acre_bdt": 1_000,
                        "labor_cost_per_acre_bdt": 1_000,
                        "irrigation_cost_per_acre_bdt": 1_000,
                        "other_cost_per_acre_bdt": 1_000,
                    }
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        # One path: the profile came from the conversation, not the plan call.
        assert body["from_conversation_session"] == "intake-complete"
        assert body["profile_used"]["target_season"] == "rabi"
        assert body["budget_bdt"] == 9_000
        assert body["profile_used"]["budget_bdt"] == 9_000
        assert body["chosen_crop_id"] == "lentil"
        assert body["selection_source"] == "farmer"
        # Ranked (cap 3), dated chosen plan (cap 4), grounded (cap 7), traced (cap 8).
        assert body["status"] == "ranked"
        assert len(body["ranked"]) == 3
        assert body["chosen_plan"]["crop_id"] == "lentil"
        assert {"land_preparation", "harvest"} <= {
            e["operation"] for e in body["chosen_plan"]["events"]
        }
        assert body["chosen_plan"]["grounding"]["status"] == "grounded"
        financial = body["evidence"]["lentil"]["financials"]
        assert financial["total_cost_bdt"] == 5_000
        assert {
            row["item"]: row["cost_per_acre_bdt"]
            for row in financial["line_items"]
        } == {
            "seed": 1_000,
            "fertilizer_bundle": 1_000,
            "labor": 1_000,
            "irrigation": 1_000,
            "other": 1_000,
        }
        assert body["trace_ids"]
        traces = client.get(
            f"/plan/preview/{body['session_id']}/traces"
        ).json()["traces"]
        assert "ranking.rank_candidates" in {t["tool"] for t in traces}
    finally:
        app.dependency_overrides.clear()


def test_consented_selected_plan_becomes_refreshable_farmer_project(monkeypatch):
    client, fake = _client(monkeypatch)
    try:
        farm = client.post(
            "/farmer/profile/session",
            json={"action": "create", "farm_name": "Shapla Project Farm"},
        ).json()
        farmer_id = farm["farmer_id"]
        draft_project = client.post(
            f"/farmer/profile/{farmer_id}/projects",
            json={"name": "Lentil · Rabi 2026"},
        ).json()["project"]
        _seed_intake(
            fake,
            "intake-project",
            {
                "soil_class": "loam",
                "drainage_condition": "well_drained",
                "water_availability": "irrigation_available",
                "budget_bdt": 80_000,
                "target_season": "rabi",
                "area_acres": 1,
                "sowing_date": "2026-11-15",
            },
        )
        response = client.post(
            "/plan/from-conversation",
            json={
                "session_id": "intake-project",
                "lat": 24.89539917,
                "lon": 89.35605547,
                "starting_depletion_mm": 40,
                "irrigation_mm_per_day": 0,
                "soil_test_class": "medium",
                "allow_assumptions": True,
                "selected_crop_id": "lentil",
                "farmer_id": farmer_id,
                "project_id": draft_project["project_id"],
                "remember_profile": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        project = body["farmer_project"]
        assert project["project_id"] == draft_project["project_id"]
        assert project["crop_id"] == "lentil"
        assert body["advanced"]["persistent_memory"]["status"] == (
            "project_saved_across_sessions"
        )
        profile = client.get(f"/farmer/profile/{farmer_id}").json()["memory"]
        assert profile["recognized"]["soil_class"] == "loam"
        assert profile["projects"][0]["project_id"] == project["project_id"]
        assert profile["location"]["lat"] == 24.895399
        canonical = SupabaseStateStore(fake).load_farm_project(
            farmer_id, project["project_id"]
        )
        assert canonical is not None
        assert canonical["plan_session_id"] == body["session_id"]
        assert canonical["status"] == "active"

        refreshed = client.post(
            f"/farmer/profile/{farmer_id}/projects/{project['project_id']}/refresh"
        )
        assert refreshed.status_code == 200
        refreshed_body = refreshed.json()
        assert refreshed_body["project"]["last_weather_check"]
        assert (
            refreshed_body["plan"]["advanced"]["project_monitor"]["status"]
            == "refreshed"
        )
        assert (
            refreshed_body["plan"]["advanced"]["pest_disease_risk"]["growth_stage"]
            != "unavailable"
        )
        traces = client.get(
            f"/plan/preview/{project['plan_session_id']}/traces"
        ).json()["traces"]
        assert "advanced.refresh_saved_project" in {
            item["tool"] for item in traces
        }
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


def test_saved_plan_scenario_changes_rainfall_and_budget_numbers(monkeypatch):
    client, fake = _client(monkeypatch)
    try:
        _seed_intake(
            fake,
            "intake-scenario",
            {
                "soil_class": "loam",
                "drainage_condition": "well_drained",
                "water_availability": "irrigation_available",
                "budget_bdt": 20_000,
                "target_season": "rabi",
                "area_acres": 1,
                "sowing_date": "2026-11-15",
            },
        )
        base = client.post(
            "/plan/from-conversation",
            json={
                "session_id": "intake-scenario",
                "lat": 24.89539917,
                "lon": 89.35605547,
                "starting_depletion_mm": 40,
                "irrigation_mm_per_day": 0,
                "soil_test_class": "medium",
                "allow_assumptions": True,
                "selected_crop_id": "maize",
            },
        )
        assert base.status_code == 200
        base_body = base.json()

        revised = client.post(
            "/plan/scenario",
            json={
                "base_session_id": base_body["session_id"],
                "lat": 24.89539917,
                "lon": 89.35605547,
                "rainfall_change_percent": -30,
                "budget_change_percent": -40,
            },
        )
        assert revised.status_code == 200
        body = revised.json()
        assert body["scenario"]["budget_before_bdt"] == 20_000
        assert body["scenario"]["budget_after_bdt"] == 12_000
        assert body["rainfall_adjustment_percent"] == -30
        assert body["scenario"]["deltas"]
        assert body["scenario"]["impacts"]
        assert body["scenario"]["summary"]
        assert all(
            item["headline"] for item in body["scenario"]["impacts"]
        )
        traces = client.get(
            f"/plan/preview/{body['session_id']}/traces"
        ).json()["traces"]
        tools = {row["tool"] for row in traces}
        assert "scenario.reuse_base_weather_snapshot" in tools
        assert "scenario.scale_rainfall" in tools
        assert "advanced.scenario_deltas" in tools
    finally:
        app.dependency_overrides.clear()
