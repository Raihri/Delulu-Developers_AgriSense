from __future__ import annotations

from fastapi.testclient import TestClient

from app import app, require_supabase
from kb.build import seed_supabase
from tests.fakes import FakeSupabaseClient


def _forecast(days: int) -> dict[str, object]:
    # A cool, dry Rabi window so the water balance can register stress.
    return {
        "source_id": "open_meteo",
        "timezone": "Asia/Dhaka",
        "daily": {
            "time": [f"2026-12-{d:02d}" for d in range(1, days + 1)],
            "temperature_2m_min": [9.0] * days,
            "temperature_2m_max": [35.0] * days,
            "precipitation_sum": [0.0] * days,
            "et0_fao_evapotranspiration": [3.5] * days,
        },
    }


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "app.fetch_forecast",
        lambda _lat, _lon, *, days: _forecast(days),
    )
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    return TestClient(app)


def _request() -> dict[str, object]:
    return {
        "lat": 24.89539917,
        "lon": 89.35605547,
        "soil_class": "loam",
        "drainage_condition": "well_drained",
        "water_availability": "irrigation_available",
        "target_season": "rabi",
        "area_acres": 1,
        "starting_depletion_mm": 40.0,
        "irrigation_mm_per_day": 0.0,
        "sowing_date": "2026-11-15",
        "soil_test_class": "medium",
        "budget_bdt": 18000,
        "allow_assumptions": True,
    }


def test_rank_produces_three_costed_weather_grounded_crops(monkeypatch) -> None:
    client = _client(monkeypatch)
    try:
        response = client.post("/plan/rank", json=_request())
        assert response.status_code == 200
        body = response.json()
        assert set(body["season_crop_ids"]) == {"maize", "lentil", "wheat"}
        assert body["status"] == "ranked"
        assert len(body["ranked"]) == 3
        assert body["chosen_crop_id"] == body["ranked"][0]["crop_id"]
        assert body["recommended_crop_id"] == body["ranked"][0]["crop_id"]
        assert body["selection_source"] == "agent_default"
        # Every ranked crop exposes reproducible evidence.
        for row in body["ranked"]:
            assert row["soil_suitability_class"] in {"S1", "S2", "S3", "N"}
            assert row["water_class"] in {"S1", "S2", "S3", "N"}
            assert isinstance(row["rough_profit_bdt"], (int, float))
            assert row["rank"] in {1, 2, 3}
            detail = body["evidence"][row["crop_id"]]["water_detail"]
            assert detail["method"].startswith("FAO-56")
            assert "totals" in detail
        # Heat/cold flags come from the exact observed temperatures.
        wheat_risk = body["evidence"]["wheat"]["temperature_risk"]
        assert "cold_stress_risk_tmin_le_10c" in wheat_risk["flags"]
        assert wheat_risk["observed_tmax_c"] == 35.0
        # The chosen crop gets a full dated land-preparation-to-harvest plan.
        plan = body["chosen_plan"]
        assert plan["crop_id"] == body["chosen_crop_id"]
        operations = {event["operation"] for event in plan["events"]}
        assert {"land_preparation", "sowing_or_transplant", "harvest"} <= operations
        assert all(
            event["source_id"] and event["source_locator"]
            for event in plan["events"]
        )
        # Budget is carried into the ranking as a per-crop fits-budget flag.
        assert body["budget_bdt"] == 18000
        for row in body["ranked"]:
            assert isinstance(row["total_cost_bdt"], (int, float))
            assert row["fits_budget"] == (row["total_cost_bdt"] <= 18000)
        # The chosen-crop advice is grounded in retrieved RAG chunks for that crop.
        grounding = plan["grounding"]
        assert grounding["status"] == "grounded"
        assert grounding["chunks"]
        assert all(chunk["crop"] == plan["crop_id"] for chunk in grounding["chunks"])
        assert grounding["semantic_model_claimed"] is False
        assert body["explanations"]
        assert all(item["based_on"] for item in body["explanations"])
        assert all(item["trace_ids"] for item in body["explanations"])
        advanced = body["advanced"]
        assert advanced["input_scheduler"]["fertilizer"]
        assert advanced["input_scheduler"]["irrigation"]
        assert advanced["pest_disease_risk"]["risks"]
        assert advanced["scenario_simulation"]["status"] == "available"
        # Capability 8: every ranked number is backed by a visible tool trace.
        assert body["trace_ids"]
        traces = client.get(f"/plan/preview/{body['session_id']}/traces").json()["traces"]
        tools = {t["tool"] for t in traces}
        assert "weather.fetch_forecast" in tools
        assert "ranking.rank_candidates" in tools
        assert "water_balance.calculate_water_balance" in tools
        weather_trace = next(t for t in traces if t["tool"] == "weather.fetch_forecast")
        assert weather_trace["trace_type"] == "external_api"
        assert weather_trace["display_output_json"]["raw_daily_values"]["et0_fao_evapotranspiration"]
        rank_trace = next(t for t in traces if t["tool"] == "ranking.rank_candidates")
        assert rank_trace["display_output_json"]["chosen_crop_id"] == body["chosen_crop_id"]
        assert "financials.project_financials" in tools
        season_trace = next(t for t in traces if t["trace_type"] == "season_plan")
        assert season_trace["display_output_json"]["events"]
        rag_trace = next(t for t in traces if t["trace_type"] == "rag_retrieval")
        assert rag_trace["display_output_json"]["chunks"][0]["text"]
    finally:
        app.dependency_overrides.clear()


def test_rank_builds_farmer_selected_non_top_crop(monkeypatch) -> None:
    client = _client(monkeypatch)
    try:
        request = _request()
        request["selected_crop_id"] = "lentil"
        response = client.post("/plan/rank", json=request)
        assert response.status_code == 200
        body = response.json()
        assert body["recommended_crop_id"] == body["ranked"][0]["crop_id"]
        assert body["chosen_crop_id"] == "lentil"
        assert body["chosen_plan"]["crop_id"] == "lentil"
        assert body["selection_source"] == "farmer"
    finally:
        app.dependency_overrides.clear()


def test_rank_rejects_selection_outside_current_ranking(monkeypatch) -> None:
    client = _client(monkeypatch)
    try:
        request = _request()
        request["selected_crop_id"] = "boro_rice"
        response = client.post("/plan/rank", json=request)
        assert response.status_code == 409
        assert response.json()["detail"]["ranked_crop_ids"] == [
            row["crop_id"]
            for row in client.post("/plan/rank", json=_request()).json()["ranked"]
        ]
    finally:
        app.dependency_overrides.clear()


def test_rank_keeps_paddy_and_missing_water_inputs_fail_closed(monkeypatch) -> None:
    client = _client(monkeypatch)
    try:
        request = _request()
        request.update({"target_season": "boro", "starting_depletion_mm": None,
                        "irrigation_mm_per_day": None})
        response = client.post("/plan/rank", json=request)
        assert response.status_code == 200
        body = response.json()
        assert body["season_crop_ids"] == ["boro_rice"]
        assert body["status"] == "no_rankable_crops"
        assert any(
            item["crop_id"] == "boro_rice"
            and "water_suitability_unassessed" in item["missing_factors"]
            for item in body["excluded"]
        )
    finally:
        app.dependency_overrides.clear()


def test_rank_excludes_null_weather_days_without_crashing(monkeypatch) -> None:
    client = _client(monkeypatch)
    forecast = _forecast(7)
    forecast["daily"]["et0_fao_evapotranspiration"][-1] = None
    monkeypatch.setattr(
        "app.fetch_forecast",
        lambda _lat, _lon, *, days: forecast,
    )
    try:
        response = client.post("/plan/rank", json=_request())
        assert response.status_code == 200
        body = response.json()
        assert len(body["ranked"]) == 3
        coverage = body["evidence"]["maize"]["water_detail"]["forecast_coverage"]
        assert coverage["returned_day_count"] == 7
        assert coverage["used_day_count"] == 6
        assert coverage["excluded_days"][0]["missing_fields"] == [
            "et0_fao_evapotranspiration"
        ]
        assert "Open-Meteo omitted required values" in body["weather_data_notice"]
        assert body["weather_data_notice"] in body["warnings"]
    finally:
        app.dependency_overrides.clear()


def test_rank_without_water_inputs_reports_unassessed_water(monkeypatch) -> None:
    client = _client(monkeypatch)
    try:
        request = _request()
        request.update({"starting_depletion_mm": None, "irrigation_mm_per_day": None})
        response = client.post("/plan/rank", json=request)
        assert response.status_code == 200
        body = response.json()
        # Soil + profit exist but water is unassessed, so nothing ranks.
        assert body["status"] == "no_rankable_crops"
        assert (
            body["evidence"]["maize"]["water_unassessed_reason"]
            == "explicit_starting_depletion_and_irrigation_required"
        )
    finally:
        app.dependency_overrides.clear()
