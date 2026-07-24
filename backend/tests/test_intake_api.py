from fastapi.testclient import TestClient

from app import app, require_gemini, require_supabase
from kb.build import seed_supabase
from tests.fakes import FakeSupabaseClient
from tests.intake_fakes import empty_raw, extracted, fake_extractor


def test_chat_intake_returns_reviewable_fields_and_cited_context() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    raw = empty_raw()
    raw.update(
        {
            "farm_size_acres": extracted(1, "1 একর", "high"),
            "soil_class": extracted("loam", "দোআঁশ", "high"),
            "drainage_condition": extracted(
                "well_drained", "দোআঁশ জমিতে", "medium"
            ),
            "water_availability": extracted(
                "irrigation_available", "সেচ আছে", "high"
            ),
            "budget_bdt": extracted(30_000, "বাজেট 30000 টাকা", "high"),
            "target_season": extracted("rabi", "রবি মৌসুমে", "high"),
            "crop_ids": extracted(["maize"], "ভুট্টা", "high"),
            "next_field": None,
            "follow_up_question": "প্রোফাইল সম্পূর্ণ।",
        }
    )
    app.dependency_overrides[require_supabase] = lambda: fake
    app.dependency_overrides[require_gemini] = lambda: fake_extractor(raw)
    try:
        response = TestClient(app).post(
            "/intake/chat",
            json={
                "message": (
                    "রবি মৌসুমে আমার 1 একর দোআঁশ জমিতে ভুট্টা লাগাবো। "
                    "সেচ আছে, বাজেট 30000 টাকা।"
                ),
                "location": {
                    "lat": 24.89539917,
                    "lon": 89.35605547,
                    "source": "live_location",
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["missing"] == []
        assert body["plan_input"]["soil_class"] == "loam"
        assert body["plan_input"]["lat"] == 24.89539917
        assert {item["source_id"] for item in body["retrieval"]} >= {
            "ais_crop_production",
            "barc_frg_2024",
        }
        assert body["mode"] == "gemini_structured_intake_v1"
    finally:
        app.dependency_overrides.clear()


def test_trusted_live_location_does_not_call_gemini_extraction() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    raw = empty_raw()
    raw["farm_size_acres"] = extracted(
        99, "I selected my farm location", "high"
    )
    app.dependency_overrides[require_supabase] = lambda: fake
    app.dependency_overrides[require_gemini] = lambda: fake_extractor(raw)
    try:
        response = TestClient(app).post(
            "/intake/chat",
            json={
                "message": "I selected my farm location.",
                "event": "location_selected",
                "location": {
                    "lat": 24.89539917,
                    "lon": 89.35605547,
                    "source": "live_location",
                },
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "trusted_location_update_v1"
        assert body["plan_input"]["lat"] == 24.89539917
        assert body["recognized"]["area_acres"] is None
        assert body["next_field"] == "farm_size_acres"
        assert body["retrieval"] == []
        stored = next(
            row
            for row in fake.tables["farmer_session"]
            if row["id"] == body["session_id"]
        )["state_json"]
        assert "24.89539917" not in str(stored)
        assert "89.35605547" not in str(stored)
    finally:
        app.dependency_overrides.clear()


def test_trusted_live_location_works_without_gemini_configuration() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    app.dependency_overrides[require_gemini] = lambda: None
    try:
        response = TestClient(app).post(
            "/intake/chat",
            json={
                "message": "I selected my farm location.",
                "event": "location_selected",
                "location": {
                    "lat": 24.89539917,
                    "lon": 89.35605547,
                    "source": "live_location",
                },
            },
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "trusted_location_update_v1"
        assert response.json()["model"] == "not_used"
    finally:
        app.dependency_overrides.clear()


def test_intake_session_retains_verified_fields_without_raw_chat_or_coordinates() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    first_raw = empty_raw()
    first_raw.update(
        {
            "farm_size_acres": extracted(1, "1 acre", "high"),
            "soil_class": extracted("loam", "loam soil", "high"),
            "drainage_condition": extracted(
                "well_drained", "loam soil", "medium"
            ),
            "water_availability": extracted(
                "irrigation_available", "irrigation available", "high"
            ),
            "budget_bdt": extracted(30_000, "budget is 30000 taka", "high"),
            "next_field": "target_season",
            "follow_up_question": "Which season are you planning for?",
        }
    )
    app.dependency_overrides[require_supabase] = lambda: fake
    app.dependency_overrides[require_gemini] = lambda: fake_extractor(first_raw)
    client = TestClient(app)
    location = {
        "lat": 24.89539917,
        "lon": 89.35605547,
        "source": "live_location",
    }
    try:
        first = client.post(
            "/intake/chat",
            json={
                "message": (
                    "My farm is 1 acre with loam soil and irrigation available; "
                    "my budget is 30000 taka."
                ),
                "location": location,
            },
        )
        assert first.status_code == 200
        session_id = first.json()["session_id"]
        assert first.json()["next_field"] == "target_season"

        uncertain_raw = empty_raw()
        uncertain_raw.update(
            {
                "latest_answer_status": "uncertain",
                "next_field": "target_season",
                "follow_up_question": "Rabi, Boro, Kharif-1, or Kharif-2?",
            }
        )
        app.dependency_overrides[require_gemini] = lambda: fake_extractor(
            uncertain_raw
        )
        second = client.post(
            "/intake/chat",
            json={
                "message": "I am not sure",
                "location": location,
                "session_id": session_id,
            },
        )
        assert second.status_code == 200
        body = second.json()
        assert body["recognized"]["budget_bdt"] == 30_000
        assert body["recognized"]["soil_class"] == "loam"
        assert body["next_field"] == "target_season"
        assert body["assistant_message"] == (
            "কোন মাসে জমি প্রস্তুত, বপন বা রোপণ শুরু করতে চান?"
        )

        stored = next(
            row
            for row in fake.tables["farmer_session"]
            if row["id"] == session_id
        )["state_json"]
        serialized = str(stored)
        assert stored["schema_version"] == "intake_context_v1"
        assert stored["recognized"]["budget_bdt"] == 30_000
        assert stored["clarification_state"] == {
            "field": "target_season",
            "level": 1,
        }
        assert "I am not sure" not in serialized
        assert "24.89539917" not in serialized
        assert "89.35605547" not in serialized
    finally:
        app.dependency_overrides.clear()
