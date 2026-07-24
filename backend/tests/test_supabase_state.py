from __future__ import annotations

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
