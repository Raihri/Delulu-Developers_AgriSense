from __future__ import annotations

from typing import Any

from state.store import SupabaseStateStore


class PlanTraceRecorder:
    """Write minimal, safe evidence for deterministic preview computations."""

    def __init__(self, store: SupabaseStateStore, session_id: str):
        self.store = store
        self.session_id = session_id
        self.trace_ids: list[str] = []

    def record(
        self,
        *,
        step: str,
        tool: str,
        params: dict[str, Any],
        output: dict[str, Any],
        trace_type: str = "computation",
        status: str = "success",
        tool_version: str = "1",
    ) -> str:
        trace_id = self.store.append_trace(
            session_id=self.session_id,
            step=step,
            tool=tool,
            tool_version=tool_version,
            trace_type=trace_type,
            status=status,
            params=params,
            output=output,
        )
        self.trace_ids.append(trace_id)
        return trace_id


def geo_trace_output(location: dict[str, Any]) -> dict[str, Any]:
    admin = location.get("admin", {})
    return {
        "matched": bool(location.get("matched")),
        "adm3_pcode": admin.get("adm3", {}).get("pcode"),
        "aez_resolution": location.get("aez_resolution"),
        "aez_candidate_ids": [
            item["aez_id"] for item in location.get("aez_candidates", [])
        ],
    }


def weather_trace_output(weather: dict[str, Any]) -> dict[str, Any]:
    daily = weather.get("daily", {})
    times = daily.get("time", []) or []
    return {
        "source_id": weather.get("source_id"),
        "timezone": weather.get("timezone"),
        "forecast_days": len(times),
        "fields": sorted(key for key in daily if key != "time"),
        "first_day": times[0] if times else None,
        "last_day": times[-1] if times else None,
        "daily_units": weather.get("daily_units"),
        # Raw returned values a judge must be able to inspect and reproduce.
        "raw_daily_values": {
            key: daily.get(key)
            for key in (
                "time",
                "temperature_2m_min",
                "temperature_2m_max",
                "precipitation_sum",
                "et0_fao_evapotranspiration",
            )
            if key in daily
        },
    }


def retrieval_trace_output(
    soil_rows: list[dict[str, Any]],
    calendar_rows: list[dict[str, Any]],
    crop_water_rows: list[dict[str, Any]] | None = None,
    soil_water_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "tables": [
            "crop_soil_suitability",
            "crop_calendar",
            "crop_water_stage",
            "soil_water_profile",
        ],
        "soil_rows": len(soil_rows),
        "calendar_rows": len(calendar_rows),
        "crop_water_rows": len(crop_water_rows or []),
        "soil_water_rows": len(soil_water_rows or []),
    }


def recommendation_trace_output(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "crop_ids": [assessment["crop_id"] for assessment in assessments],
        "ranking_statuses": sorted(
            {assessment["ranking_status"] for assessment in assessments}
        ),
        "unassessed_crop_ids": sorted(
            assessment["crop_id"]
            for assessment in assessments
            if assessment["soil_class"] == "unassessed"
            or assessment["water_class"].startswith("unassessed")
        ),
    }


def financial_trace_output(financials: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": financials["status"],
        "crop_ids": [row["crop_id"] for row in financials.get("by_crop", [])],
        "assumptions_explicitly_accepted": True,
    }


def season_trace_output(season_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "crop_id": season_plan["crop_id"],
        "status": season_plan["status"],
        "event_count": len(season_plan["events"]),
        "missing_fields": [item["field"] for item in season_plan["missing"]],
    }
