from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db import get_database_client


class SupabaseStateStore:
    """Persist farmer session state and sanitized traces in Supabase Postgres."""

    def __init__(self, client: Any | None = None):
        self.client = client or get_database_client()

    def save_session(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> None:
        row = {
            "id": session_id,
            "user_id": user_id,
            "state_json": state,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        (
            self.client.table("farmer_session")
            .upsert(row, on_conflict="id")
            .execute()
        )

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        response = (
            self.client.table("farmer_session")
            .select("state_json")
            .eq("id", session_id)
            .limit(1)
            .execute()
        )
        return response.data[0]["state_json"] if response.data else None

    def append_trace(
        self,
        *,
        session_id: str | None,
        step: str,
        tool: str,
        tool_version: str,
        trace_type: str,
        status: str,
        params: dict[str, Any],
        output: dict[str, Any],
        user_id: str | None = None,
    ) -> str:
        row = {
            "session_id": session_id,
            "user_id": user_id,
            "step": step,
            "tool": tool,
            "tool_version": tool_version,
            "trace_type": trace_type,
            "status": status,
            "params_json": params,
            "display_output_json": output,
        }
        response = self.client.table("trace_record").insert(row).execute()
        if not response.data:
            raise RuntimeError("Supabase did not return the inserted trace record")
        return str(response.data[0]["id"])

    def list_traces(self, session_id: str) -> list[dict[str, Any]]:
        """Return the sanitized, judge-visible trace for one plan session."""
        response = (
            self.client.table("trace_record")
            .select(
                "id,step,tool,tool_version,trace_type,status,"
                "params_json,display_output_json,created_at"
            )
            .eq("session_id", session_id)
            .execute()
        )
        return response.data or []
