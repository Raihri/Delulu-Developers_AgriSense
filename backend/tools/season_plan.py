from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any


class SeasonPlanDataError(RuntimeError):
    """Raised when the reviewed calendar/fertilizer slice cannot be loaded."""


def _rows(client: Any, table: str, crop_id: str) -> list[dict[str, Any]]:
    try:
        return (
            client.table(table).select("*").eq("crop_id", crop_id).execute().data
            or []
        )
    except Exception as exc:
        raise SeasonPlanDataError(f"Could not load {table} for {crop_id}") from exc


def _as_date(sowing_date: date | str | None) -> date | None:
    if sowing_date is None or isinstance(sowing_date, date):
        return sowing_date
    try:
        return date.fromisoformat(sowing_date)
    except ValueError as exc:
        raise ValueError("sowing_date must be an ISO date (YYYY-MM-DD)") from exc


def _calendar_events(calendar: dict[str, Any]) -> list[dict[str, Any]]:
    citation = {
        "source_id": calendar["source_id"],
        "source_locator": calendar["source_locator"],
    }
    return [
        {
            "operation": "sowing_or_transplant_window",
            "status": "provisional",
            "date": None,
            "month_window": {
                "start_month": calendar["sow_start_month"],
                "end_month": calendar["sow_end_month"],
            },
            "timing": calendar["window_text"],
            **citation,
        },
        {
            "operation": "harvest_window",
            "status": "provisional",
            "date": None,
            "month_window": {
                "start_month": calendar["harvest_start_month"],
                "end_month": calendar["harvest_end_month"],
            },
            "timing": calendar["window_text"],
            **citation,
        },
    ]


def _rate(row: dict[str, Any], *, fraction: float = 1.0) -> dict[str, Any]:
    return {
        "nutrient": row["nutrient"],
        "rate_min": round(float(row["rate_min"]) * fraction, 6),
        "rate_max": round(float(row["rate_max"]) * fraction, 6),
        "unit": row["canonical_unit"],
        "seasonal_fraction": fraction,
    }


def _fertilizer_event(
    rows: list[dict[str, Any]], sowing_date: date | None = None
) -> dict[str, Any]:
    first = rows[0]
    event = {
        "operation": "fertilizer_application",
        "status": "provisional",
        "date": None,
        "timing": first["application_timing"],
        "date_status": "not_calculable_from_curated_timing",
        "rates": [_rate(row) for row in rows],
        "source_id": first["source_id"],
        "source_locator": first["source_locator"],
    }
    timing = str(first["application_timing"]).casefold()
    if sowing_date is not None and ("basal" in timing or "land preparation" in timing):
        event.update(
            {
                "status": "dated_range",
                "date_start": (sowing_date - timedelta(days=10)).isoformat(),
                "date_end": (sowing_date - timedelta(days=1)).isoformat(),
                "date_status": "placed inside the disclosed final-land-preparation window",
                "assumption": (
                    "The source specifies basal/final-land-preparation timing but not "
                    "a calendar day; the project places it in the 10 days before sowing."
                ),
            }
        )
    return event


def _maize_n_events(
    row: dict[str, Any], sowing_date: date | None
) -> list[dict[str, Any]]:
    if sowing_date is None:
        return [_fertilizer_event([row])]

    citation = {"source_id": row["source_id"], "source_locator": row["source_locator"]}
    events: list[dict[str, Any]] = [
        {
            "operation": "fertilizer_application",
            "status": "dated_range",
            "date": None,
            "date_start": (sowing_date - timedelta(days=10)).isoformat(),
            "date_end": (sowing_date - timedelta(days=1)).isoformat(),
            "timing": "One-third basal nitrogen application.",
            "date_status": "placed inside the disclosed final-land-preparation window",
            "rates": [_rate(row, fraction=1 / 3)],
            "assumption": (
                "The source specifies basal timing but not a calendar day; the "
                "project places it in the 10 days before sowing."
            ),
            **citation,
        }
    ]
    for start_days, end_days in ((50, 55), (80, 85)):
        events.append(
            {
                "operation": "fertilizer_application",
                "status": "dated_range",
                "date": None,
                "date_start": (sowing_date + timedelta(days=start_days)).isoformat(),
                "date_end": (sowing_date + timedelta(days=end_days)).isoformat(),
                "timing": f"Nitrogen top-dress {start_days}-{end_days} days after sowing.",
                "rates": [_rate(row, fraction=1 / 3)],
                **citation,
            }
        )
    return events


def _wheat_n_events(
    row: dict[str, Any], sowing_date: date | None
) -> list[dict[str, Any]]:
    citation = {"source_id": row["source_id"], "source_locator": row["source_locator"]}
    events: list[dict[str, Any]] = [
        {
            "operation": "fertilizer_application",
            "status": "dated_range" if sowing_date is not None else "provisional",
            "date": None,
            "timing": "Two-thirds basal nitrogen at final land preparation.",
            "date_status": (
                "placed inside the disclosed final-land-preparation window"
                if sowing_date is not None
                else "basal timing is cited but not a numeric date rule"
            ),
            "rates": [_rate(row, fraction=2 / 3)],
            **citation,
        }
    ]
    if sowing_date is not None:
        events[0].update(
            {
                "date_start": (sowing_date - timedelta(days=10)).isoformat(),
                "date_end": (sowing_date - timedelta(days=1)).isoformat(),
                "assumption": (
                    "The source specifies final-land-preparation timing but not a "
                    "calendar day; the project places it in the 10 days before sowing."
                ),
            }
        )
    if sowing_date is None:
        return events
    # FRG p75: remaining one-third N at 17-21 DAS after the first irrigation.
    events.append(
        {
            "operation": "fertilizer_application",
            "status": "dated_range",
            "date": None,
            "date_start": (sowing_date + timedelta(days=17)).isoformat(),
            "date_end": (sowing_date + timedelta(days=21)).isoformat(),
            "timing": "Remaining one-third nitrogen 17-21 days after sowing, after first irrigation.",
            "rates": [_rate(row, fraction=1 / 3)],
            **citation,
        }
    )
    return events


def _dated_operation_timeline(
    stage_rows: list[dict[str, Any]],
    sowing_date: date,
    calendar: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build a land-preparation-to-harvest timeline from curated stage seeds.

    Stage transitions and the harvest date come from the reviewed CROPWAT stage
    durations; land preparation and the sowing anchor are cited to the reviewed
    crop calendar. Irrigation, weed and pest entries are dated scouting
    checkpoints tied to phenological stages, not prescribed products or depths.
    """

    ordered = sorted(stage_rows, key=lambda row: int(row["stage_order"]))
    if not ordered:
        return []
    stage_cite = {
        "source_id": ordered[0]["source_id"],
        "source_locator": ordered[0]["source_locator"],
    }
    cal_cite = {
        "source_id": calendar["source_id"],
        "source_locator": calendar["source_locator"],
    }

    def at(days: int) -> str:
        return (sowing_date + timedelta(days=days)).isoformat()

    events: list[dict[str, Any]] = [
        {
            "operation": "land_preparation",
            "status": "dated_range",
            "date": None,
            "date_start": (sowing_date - timedelta(days=10)).isoformat(),
            "date_end": (sowing_date - timedelta(days=1)).isoformat(),
            "timing": "Final land preparation and basal application window before sowing.",
            "assumption": (
                "A disclosed project scheduling window used to turn the cited "
                "pre-sowing sequence into dates."
            ),
            **cal_cite,
        },
        {
            "operation": "sowing_or_transplant",
            "status": "dated",
            "date": at(0),
            "timing": "Sowing/transplanting on the anchor date.",
            **cal_cite,
        },
    ]

    cumulative = 0
    stage_start: dict[str, int] = {}
    for row in ordered:
        stage_start[row["stage"]] = cumulative
        events.append(
            {
                "operation": f"stage_start_{row['stage']}",
                "status": "dated",
                "date": at(cumulative),
                "timing": (
                    f"{row['stage'].title()} stage begins "
                    f"(~{int(float(row['duration_days']))} days)."
                ),
                **stage_cite,
            }
        )
        cumulative += int(float(row["duration_days"]))
    total_days = cumulative

    for stage in ("development", "mid"):
        if stage in stage_start:
            events.append(
                {
                    "operation": "irrigation_checkpoint",
                    "status": "dated",
                    "date": at(stage_start[stage]),
                    "stage": stage,
                    "timing": (
                        f"Assess irrigation need at the {stage} stage "
                        "(rising crop water demand)."
                    ),
                    **stage_cite,
                }
            )
    if "development" in stage_start:
        events.append(
            {
                "operation": "weed_checkpoint",
                "status": "dated",
                "date": at(stage_start["development"]),
                "timing": "Weed scouting during the early vegetative/development stage.",
                **stage_cite,
            }
        )
    if "mid" in stage_start:
        events.append(
            {
                "operation": "pest_checkpoint",
                "status": "dated",
                "date": at(stage_start["mid"]),
                "timing": "Pest and disease scouting during the mid-season canopy stage.",
                **stage_cite,
            }
        )
    events.append(
        {
            "operation": "harvest",
            "status": "dated",
            "date": at(total_days),
            "timing": f"Expected harvest ~{total_days} days after sowing (CROPWAT stage sum).",
            **stage_cite,
        }
    )
    return events


def _select_fertilizer_rows(
    crop_id: str,
    rows: list[dict[str, Any]],
    *,
    soil_test_class: str | None,
    variety_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if soil_test_class is None:
        return [], [{
            "field": "soil_test_class",
            "reason": (
                "A laboratory soil-test class is required before selecting "
                "fertilizer rates."
            ),
        }]
    eligible = [row for row in rows if row["soil_test_class"] == soil_test_class]
    if variety_id is not None:
        selected = [
            row
            for row in eligible
            if row["variety_id"] in {variety_id, "all"}
        ]
        return selected, ([] if selected else [{
            "field": "fertilizer_rows",
            "reason": "No reviewed fertilizer row matches this crop, variety and soil-test class.",
        }])

    general_rows = [row for row in eligible if row["variety_id"] == "all"]
    if general_rows:
        return general_rows, []
    varieties = sorted({str(row["variety_id"]) for row in eligible})
    if varieties:
        return [], [{
            "field": "variety_id",
            "reason": "A variety is required because reviewed fertilizer rows are variety-specific.",
        }]
    return [], [{
        "field": "soil_test_class",
        "reason": "No reviewed fertilizer row matches this soil-test class.",
    }]


def build_season_plan(
    client: Any,
    crop_id: str,
    *,
    sowing_date: date | str | None = None,
    variety_id: str | None = None,
    soil_test_class: str | None = None,
) -> dict[str, Any]:
    """Build cited calendar/fertilizer events without fabricating dates.

    Calendar entries always remain month windows. A supplied sowing date produces
    real dates only for maize nitrogen's explicitly curated DAS ranges.
    """

    normalized_sowing_date = _as_date(sowing_date)
    calendar_rows = _rows(client, "crop_calendar", crop_id)
    if len(calendar_rows) != 1:
        raise ValueError(f"Expected exactly one reviewed calendar row for {crop_id!r}")

    fertilizer_rows, missing = _select_fertilizer_rows(
        crop_id,
        _rows(client, "fertilizer_recommendation", crop_id),
        soil_test_class=soil_test_class,
        variety_id=variety_id,
    )
    events = _calendar_events(calendar_rows[0])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fertilizer_rows:
        if crop_id == "maize" and row["nutrient"] == "N":
            events.extend(_maize_n_events(row, normalized_sowing_date))
        elif crop_id == "wheat" and row["nutrient"] == "N":
            events.extend(_wheat_n_events(row, normalized_sowing_date))
        else:
            grouped[str(row["application_timing"])].append(row)
    events.extend(
        _fertilizer_event(rows, normalized_sowing_date) for rows in grouped.values()
    )

    if normalized_sowing_date is not None:
        stage_rows = _rows(client, "crop_water_stage", crop_id)
        events.extend(
            _dated_operation_timeline(
                stage_rows, normalized_sowing_date, calendar_rows[0]
            )
        )

    has_dated_event = any(
        event["status"] in {"dated_range", "dated"} for event in events
    )
    return {
        "crop_id": crop_id,
        "variety_id": variety_id,
        "soil_test_class": soil_test_class,
        "sowing_date": (
            normalized_sowing_date.isoformat() if normalized_sowing_date else None
        ),
        "status": "mixed" if has_dated_event else "provisional",
        "fertilizer_status": "included" if fertilizer_rows else "missing_inputs",
        "events": events,
        "missing": (
            missing
            if normalized_sowing_date is not None
            else [
                *missing,
                {
                    "field": "sowing_date",
                    "reason": "No sowing date was supplied; calendar windows and non-numeric timing remain provisional.",
                },
            ]
        ),
    }
