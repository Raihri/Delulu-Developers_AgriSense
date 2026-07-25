from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from state.store import SupabaseStateStore
from tests.fakes import FakeSupabaseClient


def test_supabase_session_and_trace_round_trip() -> None:
    fake = FakeSupabaseClient()
    store = SupabaseStateStore(fake)
    store.save_session("session-1", {"crop": "maize"})
    assert store.load_session("session-1") == {"crop": "maize"}

    trace_id = store.append_trace(
        session_id="session-1",
        step="water",
        tool="calculate_water_balance",
        tool_version="1",
        trace_type="computation",
        status="success",
        params={"days": 1},
        output={"water_class": "S1"},
    )
    assert trace_id.startswith("fake-trace_record-")
    traces = store.list_traces("session-1")
    assert len(traces) == 1
    assert traces[0]["tool"] == "calculate_water_balance"

    farmer_id = "32ec2f05-ed1c-49e5-9db2-9daa77d2c301"
    store.save_farmer_profile(
        farmer_id,
        {"recognized": {"soil_class": "loam"}, "conversation_history": []},
    )
    assert store.load_farmer_profile(farmer_id) == {
        "recognized": {"soil_class": "loam"},
        "conversation_history": [],
    }
    project = {
        "project_id": "project-1",
        "name": "North field",
        "status": "draft",
        "access_mode": "farm",
        "intake_session_id": None,
        "plan_session_id": None,
    }
    store.save_farm_project(farmer_id, project)
    assert store.load_farm_project(farmer_id, "project-1") == project
    assert store.list_farm_projects(farmer_id) == [project]
    assert store.load_farm_project("another-farmer", "project-1") is None
    stored_project_row = fake.tables["farm_project"][0]
    assert stored_project_row["intake_session_id"] is None
    assert stored_project_row["plan_session_id"] is None

    project["plan_session_id"] = "plan-project-1"
    store.save_session("plan-project-1", {"schema_version": "plan_rank_v1"})
    store.save_farm_project(farmer_id, project)
    stored_project_row = fake.tables["farm_project"][0]
    assert stored_project_row["plan_session_id"] == "plan-project-1"


def test_state_store_normalizes_database_native_values_for_jsonb() -> None:
    fake = FakeSupabaseClient()
    store = SupabaseStateStore(fake)
    value = {
        "rate": Decimal("41.5"),
        "date": date(2026, 10, 1),
        "farmer_id": UUID("32ec2f05-ed1c-49e5-9db2-9daa77d2c301"),
    }

    store.save_session("native-values", value)
    assert store.load_session("native-values") == {
        "rate": 41.5,
        "date": "2026-10-01",
        "farmer_id": "32ec2f05-ed1c-49e5-9db2-9daa77d2c301",
    }
    store.append_trace(
        session_id="native-values",
        step="structured",
        tool="supabase.structured_retrieval",
        tool_version="1",
        trace_type="structured_retrieval",
        status="success",
        params={"as_of": value["date"]},
        output={"records": [value]},
    )
    trace = store.list_traces("native-values")[0]
    assert trace["display_output_json"]["records"][0]["rate"] == 41.5
