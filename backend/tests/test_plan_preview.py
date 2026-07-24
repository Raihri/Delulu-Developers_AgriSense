from __future__ import annotations

from fastapi.testclient import TestClient

from app import app, require_supabase
from kb.build import seed_supabase
from tests.fakes import FakeSupabaseClient


def _forecast() -> dict[str, object]:
    return {
        "source_id": "open_meteo",
        "request": {"latitude": 24.8, "longitude": 89.3},
        "request_url": "https://api.open-meteo.com/private-coordinates",
        "timezone": "Asia/Dhaka",
        "daily_units": {
            "precipitation_sum": "mm",
            "et0_fao_evapotranspiration": "mm",
        },
        "daily": {
            "time": ["2026-07-25", "2026-07-26"],
            "temperature_2m_min": [25.0, 25.2],
            "temperature_2m_max": [32.0, 32.2],
            "precipitation_sum": [4.0, 0.0],
            "et0_fao_evapotranspiration": [3.5, 3.7],
        },
    }


def _install_forecast(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.controller.fetch_forecast",
        lambda _lat, _lon, *, days: _forecast(),
    )


def _preview_client() -> TestClient:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    return TestClient(app)


def _request(*, allow_assumptions: bool) -> dict[str, object]:
    return {
        "lat": 24.89539917,
        "lon": 89.35605547,
        "soil_class": "loam",
        "drainage_condition": "well_drained",
        "water_availability": "rainfed",
        "area_acres": 1,
        "allow_assumptions": allow_assumptions,
        "session_id": "preview-test-session",
    }


def test_plan_preview_preserves_gates_and_unassessed_states(monkeypatch) -> None:
    _install_forecast(monkeypatch)
    client = _preview_client()
    try:
        response = client.post("/plan/preview", json=_request(allow_assumptions=False))

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["location"]["admin"]["adm3"]["pcode"] == "BD50100020"
        assert body["location"]["point_aez_resolved"] is False
        assert body["session_id"] == "preview-test-session"
        assert len(body["trace_ids"]) == 8
        assert body["weather_snapshot"]["source_id"] == "open_meteo"
        assert "request_url" not in body["weather_snapshot"]
        assert body["season_events"]["status"] == "provisional"
        assert {plan["crop_id"] for plan in body["season_events"]["by_crop"]} == {
            "boro_rice",
            "maize",
            "lentil",
            "wheat",
        }
        assert all(
            event["source_id"] and event["source_locator"]
            for event in body["season_events"]["events"]
        )
        assert body["financials"]["status"] == "blocked_until_assumption_opt_in"
        assert "by_crop" not in body["financials"]
        assert {item["field"] for item in body["missing"]} == {
            "soil_test_class",
            "sowing_date",
        }
        assert {row["crop_id"] for row in body["assessments"]} == {
            "boro_rice",
            "maize",
            "lentil",
            "wheat",
        }
        boro = next(
            row for row in body["assessments"] if row["crop_id"] == "boro_rice"
        )
        assert boro["soil_class"] == "unassessed"
        assert boro["water_class"] == "unassessed_paddy_model"
        assert any(
            item["crop_id"] == "boro_rice"
            and item["factor"] == "soil_suitability"
            and item["status"] == "unassessed"
            for item in body["unassessed"]
        )
        assert all(
            row["ranking_status"]
            == "not_ranked_until_all_limiting_factors_are_available"
            for row in body["assessments"]
        )
        maize = next(row for row in body["assessments"] if row["crop_id"] == "maize")
        assert maize["soil_evidence"]["source_id"]
        assert maize["calendar"]["source_locator"]

        saved = client.get("/plan/preview/preview-test-session")
        assert saved.status_code == 200
        state = saved.json()
        assert state["session_id"] == "preview-test-session"
        assert state["trace_ids"] == body["trace_ids"]
        assert "lat" not in state
        assert "lon" not in state
    finally:
        app.dependency_overrides.clear()


def test_plan_preview_includes_financials_only_after_opt_in(monkeypatch) -> None:
    _install_forecast(monkeypatch)
    client = _preview_client()
    try:
        response = client.post("/plan/preview", json=_request(allow_assumptions=True))

        assert response.status_code == 200
        financials = response.json()["financials"]
        assert financials["status"] == "included_provisional_assumptions"
        assert {row["crop_id"] for row in financials["by_crop"]} == {
            "boro_rice",
            "maize",
            "lentil",
            "wheat",
        }
        assert all(
            row["assumption_gate"] == "explicitly_accepted"
            for row in financials["by_crop"]
        )
        assert all(
            "rough_financials" not in row for row in response.json()["assessments"]
        )
        assert len(response.json()["trace_ids"]) == 9
    finally:
        app.dependency_overrides.clear()


def test_plan_preview_accepts_season_inputs_without_storing_raw_coordinates(
    monkeypatch,
) -> None:
    _install_forecast(monkeypatch)
    client = _preview_client()
    try:
        request = _request(allow_assumptions=False)
        request.update(
            {
                "session_id": "preview-dated-session",
                "sowing_date": "2026-10-01",
                "soil_test_class": "medium",
            }
        )
        response = client.post("/plan/preview", json=request)
        assert response.status_code == 200
        maize = next(
            plan
            for plan in response.json()["season_events"]["by_crop"]
            if plan["crop_id"] == "maize"
        )
        assert maize["status"] == "mixed"
        assert any(
            event.get("date_start") == "2026-11-20" for event in maize["events"]
        )

        state = client.get("/plan/preview/preview-dated-session").json()
        serialized = str(state)
        assert "24.89539917" not in serialized
        assert "89.35605547" not in serialized
        assert "postgresql" not in serialized
    finally:
        app.dependency_overrides.clear()


def test_plan_preview_trace_endpoint_returns_sanitized_records(monkeypatch) -> None:
    _install_forecast(monkeypatch)
    client = _preview_client()
    try:
        preview = client.post(
            "/plan/preview",
            json=_request(allow_assumptions=False),
        )
        assert preview.status_code == 200
        session_id = preview.json()["session_id"]

        response = client.get(f"/plan/preview/{session_id}/traces")
        assert response.status_code == 200
        traces = response.json()["traces"]
        assert len(traces) == 8
        assert traces[0]["tool"] == "geo.resolve_location"
        assert "lat" not in traces[0]["params_json"]
        # Distinct trace types and raw weather values are now exposed.
        weather = next(t for t in traces if t["tool"] == "weather.fetch_forecast")
        assert weather["trace_type"] == "external_api"
        assert weather["display_output_json"]["raw_daily_values"]["precipitation_sum"]
        assert any(t["trace_type"] == "structured_retrieval" for t in traces)
    finally:
        app.dependency_overrides.clear()


def test_plan_preview_filters_candidates_by_target_season(monkeypatch) -> None:
    _install_forecast(monkeypatch)
    client = _preview_client()
    try:
        request = _request(allow_assumptions=False)
        request.update(
            {
                "session_id": "preview-boro-only",
                "target_season": "boro",
            }
        )

        response = client.post("/plan/preview", json=request)

        assert response.status_code == 200
        body = response.json()
        assert [item["crop_id"] for item in body["assessments"]] == ["boro_rice"]
        assert [
            item["crop_id"] for item in body["season_events"]["by_crop"]
        ] == ["boro_rice"]
        assert body["financials"]["status"] == "blocked_until_assumption_opt_in"
    finally:
        app.dependency_overrides.clear()


def test_plan_preview_reports_weather_missing_only_when_live_fetch_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "agent.controller.fetch_forecast",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )
    client = _preview_client()
    try:
        response = client.post(
            "/plan/preview",
            json=_request(allow_assumptions=False),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["weather_snapshot"] is None
        assert "weather_snapshot" in {
            item["field"] for item in body["missing"]
        }
        assert any("Open-Meteo" in warning for warning in body["warnings"])
    finally:
        app.dependency_overrides.clear()


def test_rainfed_preview_uses_structured_cropwat_seeds_without_scoring(
    monkeypatch,
) -> None:
    _install_forecast(monkeypatch)
    client = _preview_client()
    try:
        request = _request(allow_assumptions=False)
        request["target_season"] = "rabi"
        response = client.post("/plan/preview", json=request)

        assert response.status_code == 200
        assessments = response.json()["assessments"]
        assert {item["crop_id"] for item in assessments} == {"maize", "lentil", "wheat"}
        assert all(
            item["water_class"] == "unassessed_initial_soil_depletion"
            for item in assessments
        )
        assert all(
            item["water_evidence"]["soil_source_id"] == "fao_cropwat"
            and item["water_evidence"]["safety_status"] == "provisional"
            for item in assessments
        )
        assert "irrigation_plan" not in {
            item["field"] for item in response.json()["missing"]
        }
    finally:
        app.dependency_overrides.clear()
