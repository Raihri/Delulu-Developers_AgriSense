"""Assemble a costed, weather-grounded crop ranking for one declared season.

This composes the existing reviewed tools without weakening any fail-closed gate:

* soil suitability comes from the curated ``crop_soil_suitability`` slice;
* the water class comes from the real FAO-56 daily balance fed by the live
  Open-Meteo ET0/rainfall series and the CROPWAT provisional Kc/soil seeds;
* rough profit comes from the explicit-assumption financial engine; and
* paddy rice stays unassessed because its water model is not curated.

A crop enters the ranking only when soil, water and profit are all present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from config import CURATED_ROOT
from tools.agro_score import build_etc_series, summarize_weather, temperature_risk
from tools.financials import project_financials
from tools.ranking import rank_candidates
from tools.water_balance import UnsupportedWaterModelError, calculate_water_balance


def _load_depletion_fractions() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(
        (Path(CURATED_ROOT) / "water_assumptions.yaml").read_text(encoding="utf-8")
    )
    return data.get("crop_critical_depletion_fraction", {}).get("values", {})


def _soil_suitability(
    soil_rows: list[dict[str, Any]],
    crop_id: str,
    soil_class: str,
    drainage_condition: str | None,
) -> tuple[str | None, dict[str, str] | None]:
    if drainage_condition is None:
        return None, None
    match = next(
        (
            row
            for row in soil_rows
            if row["crop_id"] == crop_id
            and row["drainage_condition"] == drainage_condition
            and row["soil_class"] in {soil_class, "any"}
        ),
        None,
    )
    if match is None:
        return None, None
    return match["suitability_class"], {
        "source_id": match["source_id"],
        "source_locator": match["source_locator"],
    }


def _taw_mm(
    soil_water_rows: list[dict[str, Any]],
    crop_water_rows: list[dict[str, Any]],
    soil_class: str,
) -> tuple[float | None, dict[str, str] | None]:
    profile = next(
        (row for row in soil_water_rows if row["soil_class"] == soil_class), None
    )
    if profile is None or not crop_water_rows:
        return None, None
    tam_per_m = float(profile["total_available_moisture_mm_per_m"])
    max_root = max(float(row["root_depth_end_m"]) for row in crop_water_rows)
    return round(tam_per_m * max_root, 4), {
        "soil_source_id": profile["source_id"],
        "soil_source_locator": profile["source_locator"],
    }


def build_ranking(
    *,
    crop_ids: list[str],
    soil_class: str,
    drainage_condition: str | None,
    water_availability: str | None,
    area_acres: float,
    weather_daily: dict[str, Any] | None,
    starting_depletion_mm: float | None,
    irrigation_mm_per_day: float | None,
    budget_bdt: float | None = None,
    allow_assumptions: bool = False,
    financial_overrides: dict[str, dict[str, float]] | None = None,
    soil_rows: list[dict[str, Any]],
    crop_water_rows: list[dict[str, Any]],
    soil_water_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    yield_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    depletion_fractions = _load_depletion_fractions()
    weather_summary = (
        summarize_weather(weather_daily) if weather_daily else None
    )

    candidates: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    for crop_id in crop_ids:
        crop_stage_rows = [
            row for row in crop_water_rows if row["crop_id"] == crop_id
        ]
        suitability, soil_evidence = _soil_suitability(
            soil_rows, crop_id, soil_class, drainage_condition
        )
        water_class: str | None = None
        water_detail: dict[str, Any] | None = None
        water_reason: str | None = None

        if crop_id == "boro_rice":
            water_reason = "unassessed_paddy_model"
        elif weather_daily is None:
            water_reason = "weather_snapshot_missing"
        elif starting_depletion_mm is None or irrigation_mm_per_day is None:
            water_reason = "explicit_starting_depletion_and_irrigation_required"
        elif crop_id not in depletion_fractions or not crop_stage_rows:
            water_reason = "no_reviewed_crop_water_parameters"
        else:
            taw, taw_evidence = _taw_mm(
                soil_water_rows, crop_stage_rows, soil_class
            )
            if taw is None:
                water_reason = "no_reviewed_soil_water_profile"
            else:
                series = build_etc_series(crop_stage_rows, weather_daily)
                excluded_weather_days = [
                    {
                        "date": day.get("date"),
                        "missing_fields": [
                            field
                            for field, value in (
                                ("et0_fao_evapotranspiration", day.get("et0_mm")),
                                ("precipitation_sum", day.get("rain_mm")),
                                ("crop_coefficient", day.get("kc")),
                            )
                            if value is None
                        ],
                    }
                    for day in series
                    if day.get("etc_mm") is None or day.get("rain_mm") is None
                ]
                days = [
                    {
                        "etc_mm": day["etc_mm"],
                        "rain_mm": day["rain_mm"],
                        "irrigation_mm": irrigation_mm_per_day,
                    }
                    for day in series
                    if day["etc_mm"] is not None and day["rain_mm"] is not None
                ]
                if not days:
                    water_reason = "weather_daily_missing_required_values"
                else:
                    try:
                        balance = calculate_water_balance(
                            days,
                            taw_mm=taw,
                            depletion_fraction=float(
                                depletion_fractions[crop_id]["p"]
                            ),
                            starting_depletion_mm=starting_depletion_mm,
                            crop_id=crop_id,
                        )
                        water_class = balance["water_class"]
                        water_detail = {
                            "taw_mm": taw,
                            "depletion_fraction": float(
                                depletion_fractions[crop_id]["p"]
                            ),
                            "stress_day_fraction": balance["stress_day_fraction"],
                            "totals": balance["totals"],
                            "method": balance["method"],
                            "method_source": balance["method_source"],
                            "method_locator": balance["method_locator"],
                            "water_class_policy": balance["water_class_policy"],
                            "forecast_coverage": {
                                "returned_day_count": len(series),
                                "used_day_count": len(days),
                                "excluded_days": excluded_weather_days,
                            },
                            "inputs": {
                                "starting_depletion_mm": starting_depletion_mm,
                                "irrigation_mm_per_day": irrigation_mm_per_day,
                                "daily_etc_rain_irrigation": days,
                            },
                            "days": balance["days"],
                            **(taw_evidence or {}),
                        }
                    except UnsupportedWaterModelError:
                        water_reason = "unassessed_paddy_model"

        rough_profit: float | None = None
        financial: dict[str, Any] | None = None
        crop_cost = [row for row in cost_rows if row["crop_id"] == crop_id]
        crop_yield = [row for row in yield_rows if row["crop_id"] == crop_id]
        fits_budget: bool | None = None
        total_cost: float | None = None
        if allow_assumptions and crop_cost and crop_yield:
            financial = project_financials(
                crop_id,
                area_acres,
                allow_assumptions=True,
                overrides=(financial_overrides or {}).get(crop_id),
                cost_rows=crop_cost,
                yield_rows=crop_yield,
            )
            rough_profit = financial["net_profit_bdt"]
            total_cost = financial["total_cost_bdt"]
            if budget_bdt is not None:
                fits_budget = total_cost <= budget_bdt

        risk = (
            temperature_risk(weather_summary, crop_id)
            if weather_summary is not None
            else None
        )
        candidates.append(
            {
                "crop_id": crop_id,
                "soil_suitability_class": suitability,
                "water_class": water_class,
                "rough_profit_bdt": rough_profit,
                "temperature_risk": risk,
            }
        )
        evidence[crop_id] = {
            "soil_evidence": soil_evidence,
            "water_detail": water_detail,
            "water_unassessed_reason": water_reason,
            "financials": financial,
            "total_cost_bdt": total_cost,
            "fits_budget": fits_budget,
            "temperature_risk": risk,
        }

    ranking = rank_candidates(candidates)
    ranking["weather_summary"] = weather_summary
    ranking["evidence"] = evidence
    ranking["budget_bdt"] = budget_bdt
    incomplete_coverage = next(
        (
            detail["water_detail"]["forecast_coverage"]
            for detail in evidence.values()
            if detail.get("water_detail")
            and detail["water_detail"]["forecast_coverage"]["excluded_days"]
        ),
        None,
    )
    ranking["weather_data_notice"] = (
        (
            f"Open-Meteo omitted required values on "
            f"{len(incomplete_coverage['excluded_days'])} forecast day(s); "
            f"the water balance used the remaining "
            f"{incomplete_coverage['used_day_count']} complete day(s)."
        )
        if incomplete_coverage
        else None
    )
    for row in ranking["ranked"]:
        row["total_cost_bdt"] = evidence[row["crop_id"]]["total_cost_bdt"]
        row["fits_budget"] = evidence[row["crop_id"]]["fits_budget"]
    ranking["assumption_notice"] = (
        "Water class uses the live forecast window and CROPWAT provisional seeds; "
        "profit uses explicitly accepted editable demo assumptions, not observed "
        "market prices."
    )
    return ranking
