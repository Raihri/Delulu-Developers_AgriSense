from __future__ import annotations

from datetime import date, timedelta
from typing import Any


ACRES_PER_HECTARE = 2.4710538147

PEST_RULES: dict[str, list[dict[str, Any]]] = {
    "maize": [
        {
            "name": "leaf blight screening risk",
            "kind": "disease",
            "trigger": "wet_warm",
            "susceptible_stages": ["development", "mid"],
            "prevention": [
                "Keep drainage channels open and avoid prolonged leaf wetness.",
                "Scout lower and middle leaves twice weekly during a wet spell.",
            ],
            "treatment": [
                "Remove heavily affected leaf material where practical.",
                "Ask the local DAE office to confirm diagnosis before selecting any pesticide.",
            ],
        },
        {
            "name": "fall armyworm scouting risk",
            "kind": "pest",
            "trigger": "warm",
            "susceptible_stages": ["initial", "development"],
            "prevention": ["Inspect whorls for fresh feeding damage and frass twice weekly."],
            "treatment": [
                "Hand-remove egg masses or heavily infested whorl material on small plots.",
                "Use a currently registered control only after DAE confirmation.",
            ],
        },
    ],
    "lentil": [
        {
            "name": "Stemphylium blight screening risk",
            "kind": "disease",
            "trigger": "wet_mild",
            "susceptible_stages": ["development", "mid"],
            "prevention": [
                "Avoid standing water and scout the canopy after consecutive wet days."
            ],
            "treatment": [
                "Remove severely affected plants and improve field aeration.",
                "Seek DAE confirmation before using any fungicide.",
            ],
        },
        {
            "name": "aphid scouting risk",
            "kind": "pest",
            "trigger": "mild",
            "susceptible_stages": ["development", "mid"],
            "prevention": ["Inspect tender shoots and the underside of leaves twice weekly."],
            "treatment": [
                "Conserve natural enemies and remove heavily colonized shoots on small plots.",
                "Use a currently registered control only after DAE confirmation.",
            ],
        },
    ],
    "wheat": [
        {
            "name": "rust screening risk",
            "kind": "disease",
            "trigger": "wet_mild",
            "susceptible_stages": ["development", "mid", "late"],
            "prevention": ["Scout leaves for orange or brown pustules after wet, mild weather."],
            "treatment": [
                "Mark affected patches and seek DAE diagnosis promptly.",
                "Do not select a fungicide until current registration is confirmed.",
            ],
        },
        {
            "name": "aphid scouting risk",
            "kind": "pest",
            "trigger": "mild",
            "susceptible_stages": ["development", "mid"],
            "prevention": ["Inspect tillers and emerging heads twice weekly."],
            "treatment": [
                "Conserve natural enemies and escalate confirmed outbreaks to DAE.",
                "Use a currently registered control only after DAE confirmation.",
            ],
        },
    ],
}


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_weather_watch(
    weather_daily: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply explicit weather thresholds to near-term operations."""

    if not weather_daily:
        return {"status": "unavailable", "alerts": [], "adjusted_events": []}
    dates = list(weather_daily.get("time") or [])
    rain = list(weather_daily.get("precipitation_sum") or [])
    tmax = list(weather_daily.get("temperature_2m_max") or [])
    alerts: list[dict[str, Any]] = []
    adjusted: list[dict[str, Any]] = []

    heavy_index = next(
        (i for i, value in enumerate(rain[:4]) if value is not None and float(value) >= 25),
        None,
    )
    if heavy_index is not None and heavy_index < len(dates):
        rain_date = _parse_date(dates[heavy_index])
        alerts.append(
            {
                "trigger": "heavy_rain_within_4_days",
                "date": dates[heavy_index],
                "value": float(rain[heavy_index]),
                "unit": "mm/day",
                "action": (
                    "Delay a near-term nitrogen or irrigation operation until the "
                    "heavy-rain day has passed and the field can be reassessed."
                ),
                "source_id": "open_meteo",
                "policy": "project_weather_trigger_v1 (heavy rain >=25 mm/day)",
            }
        )
        forecast_start = _parse_date(dates[0]) if dates else None
        if rain_date is not None and forecast_start is not None:
            for event in events:
                event_date = _parse_date(event.get("date") or event.get("date_start"))
                if (
                    event_date is not None
                    and 0 <= (event_date - forecast_start).days <= 4
                    and event_date <= rain_date
                    and event.get("operation")
                    in {"fertilizer_application", "irrigation_checkpoint"}
                ):
                    revised = dict(event)
                    revised["original_date"] = event_date.isoformat()
                    resume_date = rain_date + timedelta(days=1)
                    if event.get("date"):
                        revised["date"] = resume_date.isoformat()
                    if event.get("date_start"):
                        original_end = _parse_date(event.get("date_end"))
                        duration = (
                            max(0, (original_end - event_date).days)
                            if original_end is not None
                            else 0
                        )
                        revised["date_start"] = resume_date.isoformat()
                        revised["date_end"] = (
                            resume_date + timedelta(days=duration)
                        ).isoformat()
                    revised["weather_adjustment"] = (
                        f"Move this operation to {resume_date.isoformat()} and "
                        f"reassess the field after the {rain_date.isoformat()} "
                        "heavy-rain trigger."
                    )
                    adjusted.append(revised)

    hot_index = next(
        (i for i, value in enumerate(tmax) if value is not None and float(value) >= 34),
        None,
    )
    if hot_index is not None and hot_index < len(dates):
        alerts.append(
            {
                "trigger": "heat_stress",
                "date": dates[hot_index],
                "value": float(tmax[hot_index]),
                "unit": "degC daily maximum",
                "action": (
                    "Inspect crop stress early in the day and avoid scheduling field "
                    "work during peak afternoon heat."
                ),
                "source_id": "open_meteo",
                "policy": "project_weather_trigger_v1 (tmax >=34C)",
            }
        )

    return {
        "status": "triggered" if alerts else "watching_no_trigger",
        "checked_window": {
            "date_start": dates[0] if dates else None,
            "date_end": dates[-1] if dates else None,
        },
        "alerts": alerts,
        "adjusted_events": adjusted,
    }


def build_input_scheduler(
    *,
    chosen_plan: dict[str, Any],
    financials: dict[str, Any] | None,
    area_acres: float,
    irrigation_mm_per_day: float,
) -> dict[str, Any]:
    """Convert cited per-hectare inputs into a stage/date/quantity schedule."""

    area_ha = area_acres / ACRES_PER_HECTARE
    line_items = (financials or {}).get("line_items") or []
    fertilizer_cost = next(
        (
            float(row["total_cost_bdt"])
            for row in line_items
            if row.get("item") == "fertilizer_bundle"
        ),
        None,
    )
    irrigation_cost = next(
        (
            float(row["total_cost_bdt"])
            for row in line_items
            if row.get("item") == "irrigation"
        ),
        None,
    )
    fertilizer_events = [
        event
        for event in chosen_plan.get("events", [])
        if event.get("operation") == "fertilizer_application"
    ]
    irrigation_events = [
        event
        for event in chosen_plan.get("events", [])
        if event.get("operation") == "irrigation_checkpoint"
    ]

    scheduled_fertilizer: list[dict[str, Any]] = []
    organic_options: list[dict[str, Any]] = []
    for event in fertilizer_events:
        quantities = []
        for rate in event.get("rates", []):
            minimum = float(rate.get("rate_min", 0))
            maximum = float(rate.get("rate_max", 0))
            unit = rate.get("unit")
            multiplier = area_ha if unit in {"kg/ha", "t/ha"} else area_acres
            item = {
                **rate,
                "total_min_for_farm": round(minimum * multiplier, 4),
                "total_max_for_farm": round(maximum * multiplier, 4),
                "farm_total_unit": unit.replace("/ha", "") if isinstance(unit, str) else unit,
            }
            quantities.append(item)
            if rate.get("nutrient") in {"organic_fertilizer", "rhizobium_inoculant"}:
                organic_options.append(item)
        scheduled_fertilizer.append(
            {
                "date": event.get("date"),
                "date_start": event.get("date_start"),
                "date_end": event.get("date_end"),
                "timing": event.get("timing"),
                "quantities": quantities,
                "allocated_cost_bdt": (
                    round(fertilizer_cost / len(fertilizer_events), 2)
                    if fertilizer_cost is not None and fertilizer_events
                    else None
                ),
                "source_id": event.get("source_id"),
                "source_locator": event.get("source_locator"),
            }
        )

    scheduled_irrigation = [
        {
            "date": event.get("date"),
            "stage": event.get("stage"),
            "planned_net_depth_mm": irrigation_mm_per_day,
            "action": event.get("timing"),
            "allocated_cost_bdt": (
                round(irrigation_cost / len(irrigation_events), 2)
                if irrigation_cost is not None and irrigation_events
                else None
            ),
            "source_id": event.get("source_id"),
            "source_locator": event.get("source_locator"),
        }
        for event in irrigation_events
    ]

    return {
        "status": "scheduled",
        "crop_id": chosen_plan.get("crop_id"),
        "soil_test_class": chosen_plan.get("soil_test_class"),
        "area_acres": area_acres,
        "area_hectares": round(area_ha, 6),
        "fertilizer": scheduled_fertilizer,
        "irrigation": scheduled_irrigation,
        "organic_alternatives": organic_options,
        "cost_basis": "project_demo_assumptions",
    }


def build_pest_disease_risk(
    *,
    crop_id: str,
    weather_daily: dict[str, Any] | None,
    area_acres: float,
    chosen_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Screen crop, current growth stage and weather; never prescribe a pesticide."""

    if not weather_daily:
        return {"status": "unavailable", "risks": []}
    raw_rain = list(weather_daily.get("precipitation_sum") or [])
    raw_tmin = list(weather_daily.get("temperature_2m_min") or [])
    raw_tmax = list(weather_daily.get("temperature_2m_max") or [])
    rain = [float(value) for value in raw_rain if value is not None]
    tmin = [float(value) for value in raw_tmin if value is not None]
    tmax = [float(value) for value in raw_tmax if value is not None]
    wet_days = sum(1 for value in rain if value >= 1)
    mean_temp = (
        (sum(tmin) + sum(tmax)) / (len(tmin) + len(tmax))
        if tmin and tmax
        else None
    )
    forecast_start = _parse_date(
        (weather_daily.get("time") or [None])[0]
        if weather_daily.get("time")
        else None
    )
    plan_events = (chosen_plan or {}).get("events") or []
    sowing_date = _parse_date((chosen_plan or {}).get("sowing_date"))
    harvest_date = next(
        (
            _parse_date(event.get("date"))
            for event in plan_events
            if event.get("operation") == "harvest"
        ),
        None,
    )
    stage_starts = sorted(
        (
            (_parse_date(event.get("date")), str(event.get("operation"))[12:])
            for event in plan_events
            if str(event.get("operation", "")).startswith("stage_start_")
            and _parse_date(event.get("date")) is not None
        ),
        key=lambda item: item[0],
    )
    growth_stage = "unavailable"
    if forecast_start is not None and sowing_date is not None:
        if forecast_start < sowing_date:
            growth_stage = "pre_sowing"
        elif harvest_date is not None and forecast_start >= harvest_date:
            growth_stage = "post_harvest"
        else:
            growth_stage = next(
                (
                    stage
                    for stage_date, stage in reversed(stage_starts)
                    if stage_date <= forecast_start
                ),
                "initial",
            )
    risks = []
    for rule in PEST_RULES.get(crop_id, []):
        trigger = rule["trigger"]
        weather_triggered = {
            "wet_warm": wet_days >= 3 and mean_temp is not None and 20 <= mean_temp <= 32,
            "wet_mild": wet_days >= 2 and mean_temp is not None and 15 <= mean_temp <= 28,
            "warm": mean_temp is not None and mean_temp >= 24,
            "mild": mean_temp is not None and 15 <= mean_temp <= 28,
        }[trigger]
        stage_applicable = growth_stage in rule["susceptible_stages"]
        triggered = weather_triggered and stage_applicable
        risks.append(
            {
                **rule,
                "risk_level": (
                    "elevated"
                    if triggered
                    else "routine_watch"
                    if stage_applicable
                    else "outside_susceptible_stage"
                ),
                "growth_stage": growth_stage,
                "stage_applicable": stage_applicable,
                "weather_triggered": weather_triggered,
                "weather_basis": {
                    "wet_days_ge_1mm": wet_days,
                    "mean_temperature_c": round(mean_temp, 3) if mean_temp is not None else None,
                    "provider_value_coverage": {
                        "rain_values_used": len(rain),
                        "rain_values_missing": len(raw_rain) - len(rain),
                        "temperature_values_used": len(tmin) + len(tmax),
                        "temperature_values_missing": (
                            len(raw_tmin) + len(raw_tmax) - len(tmin) - len(tmax)
                        ),
                    },
                },
                "estimated_scouting_cost_bdt": round(700 * area_acres, 2),
                "cost_source_id": "project_demo_assumptions",
                "weather_source_id": "open_meteo",
            }
        )
    return {
        "status": "screening_only_not_diagnosis",
        "growth_stage": growth_stage,
        "forecast_start": forecast_start.isoformat() if forecast_start else None,
        "pesticide_safety": (
            "No pesticide or dosage is recommended because the DAE registration "
            "dataset remains blocked pending a current status/cancellation cross-check."
        ),
        "risks": risks,
    }


def scenario_deltas(
    base_ranked: list[dict[str, Any]],
    revised_ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base = {row["crop_id"]: row for row in base_ranked}
    deltas = []
    for row in revised_ranked:
        prior = base.get(row["crop_id"])
        deltas.append(
            {
                "crop_id": row["crop_id"],
                "rank_before": prior.get("rank") if prior else None,
                "rank_after": row.get("rank"),
                "composite_score_before": prior.get("composite_score") if prior else None,
                "composite_score_after": row.get("composite_score"),
                "water_class_before": prior.get("water_class") if prior else None,
                "water_class_after": row.get("water_class"),
                "fits_budget_before": prior.get("fits_budget") if prior else None,
                "fits_budget_after": row.get("fits_budget"),
            }
        )
    return deltas


def scenario_impacts(
    base_ranked: list[dict[str, Any]],
    revised_ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate scenario deltas into bounded, farmer-facing consequences."""

    base = {row["crop_id"]: row for row in base_ranked}
    impacts: list[dict[str, Any]] = []
    for row in revised_ranked:
        crop_id = str(row["crop_id"])
        prior = base.get(crop_id) or {}
        rank_before = prior.get("rank")
        rank_after = row.get("rank")
        messages: list[str] = []

        if rank_before is not None and rank_after is not None:
            if rank_after < rank_before:
                rank_message = f"Moves up from #{rank_before} to #{rank_after}."
            elif rank_after > rank_before:
                rank_message = f"Moves down from #{rank_before} to #{rank_after}."
            else:
                rank_message = f"Stays at rank #{rank_after}."
            messages.append(rank_message)

        water_before = prior.get("water_class")
        water_after = row.get("water_class")
        if water_before and water_after:
            messages.append(
                f"Forecast water fit changes from {water_before} to {water_after}."
                if water_before != water_after
                else f"Forecast water fit remains {water_after}."
            )

        budget_before = prior.get("fits_budget")
        budget_after = row.get("fits_budget")
        if budget_after is True:
            messages.append(
                "Now fits the revised budget."
                if budget_before is False
                else "Still fits the revised budget."
            )
        elif budget_after is False:
            messages.append(
                "No longer fits the revised budget."
                if budget_before is True
                else "Still exceeds the revised budget."
            )

        profit_before = prior.get("rough_profit_bdt")
        profit_after = row.get("rough_profit_bdt")
        if profit_after is not None:
            if profit_before is not None and round(float(profit_before), 2) != round(
                float(profit_after), 2
            ):
                messages.append(
                    "Estimated net profit changes from "
                    f"BDT {float(profit_before):,.0f} to BDT {float(profit_after):,.0f}."
                )
            else:
                messages.append(
                    f"Estimated net profit remains about BDT {float(profit_after):,.0f} "
                    "under the current price and cost assumptions."
                )

        impacts.append(
            {
                "crop_id": crop_id,
                "rank_before": rank_before,
                "rank_after": rank_after,
                "water_class_before": water_before,
                "water_class_after": water_after,
                "fits_budget_before": budget_before,
                "fits_budget_after": budget_after,
                "rough_profit_before_bdt": profit_before,
                "rough_profit_after_bdt": profit_after,
                "headline": messages[0] if messages else "Scenario recalculated.",
                "messages": messages[1:],
                "attention": (
                    "budget"
                    if budget_after is False
                    else "water"
                    if water_before != water_after
                    else "stable"
                ),
            }
        )
    return impacts
