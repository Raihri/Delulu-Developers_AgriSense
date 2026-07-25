from fastapi.testclient import TestClient

from app import app, require_gemini, require_supabase
from kb.build import seed_supabase
from state.store import SupabaseStateStore
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


def test_trusted_location_does_not_restore_or_overwrite_saved_profile() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    farmer_id = "32ec2f05-ed1c-49e5-9db2-9daa77d2c301"
    saved_profile = {
        "schema_version": "farmer_memory_v1",
        "recognized": {
            "area_acres": 99,
            "soil_class": "clay",
            "drainage_condition": "poorly_drained",
            "water_availability": "rainfed",
            "budget_bdt": 10_000,
            "target_season": "rabi",
            "crop_ids": ["maize"],
        },
        "conversation_history": [],
        "last_intake_session_id": "old-session",
    }
    fake.table("farmer_profile").upsert(
        {
            "id": farmer_id,
            "profile_json": saved_profile,
        },
        on_conflict="id",
    ).execute()
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
                "farmer_id": farmer_id,
                "remember_profile": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["recognized"]["area_acres"] is None
        assert body["recognized"]["soil_class"] is None
        assert body["recognized"]["crop_ids"] == []
        assert body["next_field"] == "farm_size_acres"
        assert body["memory"]["status"] == "unchanged"
        saved = (
            fake.table("farmer_profile")
            .select("profile_json")
            .eq("id", farmer_id)
            .limit(1)
            .execute()
            .data[0]["profile_json"]
        )
        assert saved == saved_profile
    finally:
        app.dependency_overrides.clear()


def test_consented_farmer_memory_restores_context_across_new_sessions() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    farmer_id = "32ec2f05-ed1c-49e5-9db2-9daa77d2c301"
    complete = empty_raw()
    complete.update(
        {
            "farm_size_acres": extracted(1, "1 acre", "high"),
            "soil_class": extracted("loam", "loam", "high"),
            "drainage_condition": extracted("well_drained", "drains well", "high"),
            "water_availability": extracted(
                "irrigation_available", "irrigation", "high"
            ),
            "budget_bdt": extracted(30_000, "30000", "high"),
            "target_season": extracted("rabi", "Rabi", "high"),
            "next_field": None,
            "follow_up_question": "Ready.",
        }
    )
    app.dependency_overrides[require_supabase] = lambda: fake
    app.dependency_overrides[require_gemini] = lambda: fake_extractor(complete)
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
                    "My 1 acre loam farm drains well, has irrigation, a 30000 "
                    "budget, and I want Rabi."
                ),
                "location": location,
                "farmer_id": farmer_id,
                "remember_profile": True,
            },
        )
        assert first.status_code == 200
        assert first.json()["memory"]["status"] == "saved"

        app.dependency_overrides[require_gemini] = lambda: fake_extractor(empty_raw())
        ordinary_message = client.post(
            "/intake/chat",
            json={
                "message": "I want to start another farm.",
                "farmer_id": farmer_id,
                "remember_profile": True,
            },
        )
        assert ordinary_message.status_code == 200
        assert ordinary_message.json()["recognized"]["budget_bdt"] is None
        preserved = client.get(f"/farmer/profile/{farmer_id}").json()["memory"]
        assert preserved["recognized"]["budget_bdt"] == 30_000

        app.dependency_overrides[require_gemini] = lambda: None
        second = client.post(
            "/intake/chat",
            json={
                "message": "Restore my saved farm profile.",
                "event": "profile_restore",
                "farmer_id": farmer_id,
                "remember_profile": True,
            },
        )
        assert second.status_code == 200
        assert second.json()["mode"] == "consented_profile_restore_v1"
        assert second.json()["memory"]["status"] == "restored"
        assert second.json()["recognized"]["budget_bdt"] == 30_000
        assert second.json()["plan_input"]["lat"] == round(location["lat"], 6)
        loaded = client.get(f"/farmer/profile/{farmer_id}")
        assert loaded.status_code == 200
        assert loaded.json()["memory"]["conversation_history"]
        assert loaded.json()["memory"]["location"]["source"] == "live_location"
    finally:
        app.dependency_overrides.clear()


def test_farm_profile_session_create_logout_boundary_and_login() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    client = TestClient(app)
    try:
        created = client.post(
            "/farmer/profile/session",
            json={"action": "create", "farm_name": "Shapla Family Farm"},
        )
        assert created.status_code == 200
        body = created.json()
        farmer_id = body["farmer_id"]
        assert body["session_mode"] == "created"
        assert body["authentication_boundary"] == "opaque_demo_access_id"
        assert body["memory"]["schema_version"] == "farmer_memory_v3"
        assert body["memory"]["identity"]["farm_name"] == "Shapla Family Farm"
        assert body["memory"]["identity"]["access_mode"] == "farm"
        assert body["memory"]["projects"] == []

        project_response = client.post(
            f"/farmer/profile/{farmer_id}/projects",
            json={"name": "North field · Rabi"},
        )
        assert project_response.status_code == 200
        project = project_response.json()["project"]
        assert project["status"] == "draft"
        assert project["plan_session_id"] is None
        assert fake.tables["farm_project"][0]["farmer_id"] == farmer_id

        restored = client.post(
            "/farmer/profile/session",
            json={"action": "login", "farmer_id": farmer_id},
        )
        assert restored.status_code == 200
        assert restored.json()["session_mode"] == "restored"
        assert restored.json()["memory"]["identity"]["farm_name"] == (
            "Shapla Family Farm"
        )
        assert restored.json()["memory"]["projects"][0]["project_id"] == (
            project["project_id"]
        )

        guest = client.post(
            "/farmer/profile/session",
            json={"action": "guest"},
        )
        assert guest.status_code == 200
        assert guest.json()["session_mode"] == "guest"
        assert guest.json()["memory"]["identity"]["access_mode"] == "guest"
        assert guest.json()["authentication_boundary"] == (
            "non_resumable_guest_session"
        )

        missing = client.post(
            "/farmer/profile/session",
            json={
                "action": "login",
                "farmer_id": "db2b8ae4-0b82-44ed-8c4f-cb0e72e30b12",
            },
        )
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_intake_is_saved_inside_its_database_project() -> None:
    fake = FakeSupabaseClient()
    seed_supabase(fake, validate=False)
    app.dependency_overrides[require_supabase] = lambda: fake
    app.dependency_overrides[require_gemini] = lambda: None
    client = TestClient(app)
    try:
        farm = client.post(
            "/farmer/profile/session",
            json={"action": "create", "farm_name": "Project Farm"},
        ).json()
        farmer_id = farm["farmer_id"]
        project = client.post(
            f"/farmer/profile/{farmer_id}/projects",
            json={"name": "Rabi test project"},
        ).json()["project"]
        response = client.post(
            "/intake/chat",
            json={
                "message": "I selected my farm location.",
                "event": "location_selected",
                "location": {
                    "lat": 24.89539917,
                    "lon": 89.35605547,
                    "source": "live_location",
                },
                "farmer_id": farmer_id,
                "project_id": project["project_id"],
                "remember_profile": True,
            },
        )
        assert response.status_code == 200
        saved = SupabaseStateStore(fake).load_farm_project(
            farmer_id, project["project_id"]
        )
        assert saved is not None
        assert saved["status"] == "intake"
        assert saved["intake_session_id"] == response.json()["session_id"]
        assert saved["location"]["lat"] == 24.895399
        assert (
            client.get(f"/farmer/profile/{farmer_id}")
            .json()["memory"]["projects"][0]["project_id"]
            == project["project_id"]
        )
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
