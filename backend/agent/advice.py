from __future__ import annotations

from typing import Any


def _source_refs(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk.get("chunk_id"),
            "source_id": chunk.get("source_id"),
            "source_locator": chunk.get("source_locator"),
            "score": chunk.get("score"),
        }
        for chunk in chunks
    ]


def build_explanations(
    *,
    profile: dict[str, Any],
    ranking: dict[str, Any],
    chosen_plan: dict[str, Any],
    grounding_by_crop: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Render faithful advice from structured evidence and retrieved chunks.

    This deliberately uses templates rather than asking a model to invent prose.
    Every sentence is backed by the adjacent ``based_on`` record.
    """

    weather = ranking.get("weather_summary") or {}
    explanations: list[dict[str, Any]] = []

    for row in ranking.get("ranked", []):
        crop_id = str(row["crop_id"])
        evidence = (ranking.get("evidence") or {}).get(crop_id, {})
        chunk_refs = _source_refs(grounding_by_crop.get(crop_id, []))
        if not chunk_refs:
            # A farmer-facing recommendation is never rendered when retrieval
            # has no evidence above the disclosed threshold for that crop.
            continue
        explanations.append(
            {
                "id": f"crop-ranking:{crop_id}",
                "kind": "crop_ranking",
                "crop_id": crop_id,
                "recommendation": (
                    f"Rank {row['rank']}: {crop_id} scores {row['composite_score']:.3f}. "
                    f"The reviewed soil class is {row['soil_suitability_class']}, "
                    f"the forecast-driven water class is {row['water_class']}, and "
                    f"the assumption-based rough net profit is "
                    f"BDT {row['rough_profit_bdt']:.2f}."
                ),
                "based_on": {
                    "farm_inputs": {
                        "soil_class": profile.get("soil_class"),
                        "drainage_condition": profile.get("drainage_condition"),
                        "water_availability": profile.get("water_availability"),
                        "area_acres": profile.get("area_acres"),
                        "budget_bdt": profile.get("budget_bdt"),
                        "target_season": profile.get("target_season"),
                    },
                    "retrieved_weather": {
                        "date_start": weather.get("date_start"),
                        "date_end": weather.get("date_end"),
                        "rain_total_mm": weather.get("rain_total_mm"),
                        "et0_total_mm": weather.get("et0_total_mm"),
                        "tmin_min_c": weather.get("tmin_min_c"),
                        "tmax_max_c": weather.get("tmax_max_c"),
                    },
                    "soil_evidence": evidence.get("soil_evidence"),
                    "water_evidence": evidence.get("water_detail"),
                    "financial_inputs": evidence.get("financials"),
                    "retrieved_chunks": chunk_refs,
                    "formula": ranking.get("policy"),
                },
                "trace_ids": [],
            }
        )

    chosen_chunk_refs = _source_refs(
        grounding_by_crop.get(str(chosen_plan.get("crop_id")), [])
    )
    for index, event in enumerate(chosen_plan.get("events", []), start=1):
        when = (
            event.get("date")
            or (
                f"{event.get('date_start')} to {event.get('date_end')}"
                if event.get("date_start")
                else event.get("timing")
            )
        )
        explanations.append(
            {
                "id": f"season-event:{index}",
                "kind": "season_operation",
                "crop_id": chosen_plan.get("crop_id"),
                "recommendation": (
                    f"{event.get('operation')}: {when}. {event.get('timing', '')}"
                ).strip(),
                "based_on": {
                    "sowing_date": chosen_plan.get("sowing_date"),
                    "soil_test_class": chosen_plan.get("soil_test_class"),
                    "structured_source": {
                        "source_id": event.get("source_id"),
                        "source_locator": event.get("source_locator"),
                    },
                    "rates": event.get("rates", []),
                    "retrieved_chunks": chosen_chunk_refs,
                    "assumption": event.get("assumption"),
                },
                "trace_ids": [],
            }
        )

    return explanations
