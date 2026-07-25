from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder

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
            # Direct Postgres adapters return Decimal/date/UUID values that are
            # valid domain objects but not accepted by JSONB encoders.
            "state_json": jsonable_encoder(state),
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

    def save_farmer_profile(
        self,
        farmer_id: str,
        profile: dict[str, Any],
    ) -> None:
        """Persist a consented, bounded farm/conversation summary across sessions."""

        row = {
            "id": farmer_id,
            "profile_json": jsonable_encoder(profile),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        (
            self.client.table("farmer_profile")
            .upsert(row, on_conflict="id")
            .execute()
        )

    def load_farmer_profile(self, farmer_id: str) -> dict[str, Any] | None:
        response = (
            self.client.table("farmer_profile")
            .select("profile_json")
            .eq("id", farmer_id)
            .limit(1)
            .execute()
        )
        return response.data[0]["profile_json"] if response.data else None

    def save_farm_project(
        self,
        farmer_id: str,
        project: dict[str, Any],
    ) -> None:
        """Persist one project as a canonical row owned by a farm session."""

        now = datetime.now(UTC).isoformat()
        requested_session_ids = {
            str(value)
            for value in (
                project.get("intake_session_id"),
                project.get("plan_session_id"),
            )
            if value not in (None, "")
        }
        existing_session_ids = self._existing_session_ids(
            requested_session_ids
        )
        requested_intake_id = project.get("intake_session_id")
        requested_plan_id = project.get("plan_session_id")
        intake_session_id = (
            str(requested_intake_id)
            if requested_intake_id not in (None, "")
            and str(requested_intake_id) in existing_session_ids
            else None
        )
        plan_session_id = (
            str(requested_plan_id)
            if requested_plan_id not in (None, "")
            and str(requested_plan_id) in existing_session_ids
            else None
        )
        row = {
            "id": str(project["project_id"]),
            "farmer_id": farmer_id,
            "name": str(project["name"]),
            "status": str(project["status"]),
            "access_mode": str(project.get("access_mode") or "farm"),
            # These indexed columns are foreign keys. A legacy or just-created
            # project may carry a session ID whose parent row is not visible
            # yet; keep the full ID in project_json and link the column only
            # when the parent exists.
            "intake_session_id": intake_session_id,
            "plan_session_id": plan_session_id,
            "project_json": jsonable_encoder(project),
            "updated_at": now,
        }
        (
            self.client.table("farm_project")
            .upsert(row, on_conflict="id")
            .execute()
        )

    def _existing_session_ids(self, values: set[str]) -> set[str]:
        if not values:
            return set()
        response = (
            self.client.table("farmer_session")
            .select("id")
            .in_("id", sorted(values))
            .execute()
        )
        return {str(row["id"]) for row in response.data or [] if row.get("id")}

    def load_farm_project(
        self,
        farmer_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        response = (
            self.client.table("farm_project")
            .select("project_json")
            .eq("id", project_id)
            .eq("farmer_id", farmer_id)
            .limit(1)
            .execute()
        )
        return response.data[0]["project_json"] if response.data else None

    def list_farm_projects(self, farmer_id: str) -> list[dict[str, Any]]:
        response = (
            self.client.table("farm_project")
            .select("project_json")
            .eq("farmer_id", farmer_id)
            .execute()
        )
        projects = [
            row["project_json"]
            for row in response.data or []
            if isinstance(row.get("project_json"), dict)
        ]
        return sorted(
            projects,
            key=lambda item: str(
                item.get("last_activity_at")
                or item.get("created_at")
                or ""
            ),
            reverse=True,
        )

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
            "params_json": jsonable_encoder(params),
            "display_output_json": jsonable_encoder(output),
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
