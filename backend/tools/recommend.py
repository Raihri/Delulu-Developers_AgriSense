from __future__ import annotations

import csv
from functools import lru_cache
from typing import Any

from config import CURATED_ROOT
from tools.financials import project_financials


DEMO_CROPS = ("boro_rice", "maize", "lentil", "wheat")


@lru_cache(maxsize=1)
def _soil_rows() -> list[dict[str, str]]:
    with (CURATED_ROOT / "crop_soil_suitability.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _calendar_rows() -> dict[str, dict[str, str]]:
    with (CURATED_ROOT / "crop_calendar.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        return {row["crop_id"]: row for row in csv.DictReader(handle)}


def assess_demo_crops(
    *,
    soil_class: str,
    drainage_condition: str | None = None,
    water_availability: str | None = None,
    target_season: str | None = None,
    crop_ids: list[str] | None = None,
    weather_available: bool = False,
    area_acres: float = 1.0,
    allow_assumptions: bool = False,
    soil_rows: list[dict[str, Any]] | None = None,
    calendar_rows: list[dict[str, Any]] | dict[str, dict[str, Any]] | None = None,
    crop_water_rows: list[dict[str, Any]] | None = None,
    soil_water_rows: list[dict[str, Any]] | None = None,
    cost_rows: list[dict[str, Any]] | None = None,
    yield_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the complete dry-season demo slice without inventing missing scores."""

    available_soils = soil_rows if soil_rows is not None else _soil_rows()
    if calendar_rows is None:
        available_calendars = _calendar_rows()
    elif isinstance(calendar_rows, dict):
        available_calendars = calendar_rows
    else:
        available_calendars = {
            row["crop_id"]: row for row in calendar_rows
        }

    requested_crops = set(crop_ids or [])
    candidate_ids = [
        crop_id
        for crop_id in DEMO_CROPS
        if (not requested_crops or crop_id in requested_crops)
        and (
            target_season is None
            or available_calendars[crop_id]["season"] == target_season
        )
    ]

    results: list[dict[str, Any]] = []
    for crop_id in candidate_ids:
        relevant = [
            row
            for row in available_soils
            if row["crop_id"] == crop_id
            and drainage_condition is not None
            and row["drainage_condition"] == drainage_condition
            and row["soil_class"] in {soil_class, "any"}
        ]
        soil_classification = relevant[0]["suitability_class"] if relevant else "unassessed"
        soil_water_profile = next(
            (
                row
                for row in (soil_water_rows or [])
                if row["soil_class"] == soil_class
            ),
            None,
        )
        crop_water_profile = [
            row for row in (crop_water_rows or []) if row["crop_id"] == crop_id
        ]
        if crop_id == "boro_rice":
            water_class = "unassessed_paddy_model"
        elif water_availability == "rainfed" and weather_available:
            water_class = (
                "unassessed_initial_soil_depletion"
                if soil_water_profile and crop_water_profile
                else "unassessed_soil_hydraulic_inputs"
            )
        elif water_availability in {
            "irrigation_available",
            "surface_water_available",
            "limited",
        }:
            water_class = "unassessed_irrigation_schedule"
        else:
            water_class = "unassessed_water_source"

        result: dict[str, Any] = {
            "crop_id": crop_id,
            "soil_class": soil_classification,
            "water_class": water_class,
            "calendar": available_calendars[crop_id],
            "ranking_status": "not_ranked_until_all_limiting_factors_are_available",
        }
        if relevant:
            result["soil_evidence"] = {
                "source_id": relevant[0]["source_id"],
                "source_locator": relevant[0]["source_locator"],
            }
        if soil_water_profile and crop_water_profile:
            result["water_evidence"] = {
                "soil_source_id": soil_water_profile["source_id"],
                "soil_source_locator": soil_water_profile["source_locator"],
                "crop_source_id": crop_water_profile[0]["source_id"],
                "crop_source_locator": crop_water_profile[0]["source_locator"],
                "safety_status": "provisional",
                "local_observation": False,
            }
        if allow_assumptions:
            result["rough_financials"] = project_financials(
                crop_id,
                area_acres,
                allow_assumptions=True,
                cost_rows=cost_rows,
                yield_rows=yield_rows,
            )
        results.append(result)
    return {
        "target_window": target_season or "Bangladesh winter/dry-season demo",
        "candidates": results,
        "warning": (
            (
                "No demo crop matches the selected season and explicit crop filters."
                if not results
                else "These are transparent assessments, not a fabricated ranking. "
                "Ranking stays disabled until every limiting factor is available."
            )
        ),
    }
