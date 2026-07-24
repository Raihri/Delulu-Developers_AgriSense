"""Deterministic crop ranking for the reviewed same-season demo slice.

The ranking never fabricates a missing limiting factor. A crop is ranked only
when soil suitability, a weather-driven water class and a rough profit are all
present. Any crop missing one of those is returned in ``excluded`` with a
machine-readable reason, preserving the project's fail-closed contract while
still producing the ordered top list Tier 0 requires when the inputs exist.
"""

from __future__ import annotations

from typing import Any

from tools.agro_score import SUITABILITY_SCORE


# Weights sum to 1.0. Soil and water are the hard agronomic limiters; rough
# profit only breaks ties among agronomically viable crops.
WEIGHT_SOIL = 0.40
WEIGHT_WATER = 0.40
WEIGHT_PROFIT = 0.20

RANKING_POLICY = "deterministic_project_policy_v1 (soil 0.40, water 0.40, profit 0.20)"


def _profit_scores(profits: list[float]) -> dict[int, float]:
    """Min-max normalize rough profit across the comparable crops (0..1)."""

    if not profits:
        return {}
    low, high = min(profits), max(profits)
    span = high - low
    return {
        index: (1.0 if span == 0 else (value - low) / span)
        for index, value in enumerate(profits)
    }


def rank_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank crops that have every limiting factor; exclude the rest with reasons.

    Each candidate must provide ``crop_id`` and may provide:
      - ``soil_suitability_class`` in {S1,S2,S3,N} (else soil is unassessed)
      - ``water_class`` in {S1,S2,S3,N} (from the FAO-56 balance; else unassessed)
      - ``rough_profit_bdt`` float (else profit is unavailable)
      - ``temperature_risk`` optional dict of sourced flags (does not gate ranking)
    """

    rankable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for candidate in candidates:
        crop_id = candidate["crop_id"]
        soil_class = candidate.get("soil_suitability_class")
        water_class = candidate.get("water_class")
        profit = candidate.get("rough_profit_bdt")
        reasons: list[str] = []
        if soil_class not in SUITABILITY_SCORE:
            reasons.append("soil_suitability_unassessed")
        if water_class not in SUITABILITY_SCORE:
            reasons.append("water_suitability_unassessed")
        if profit is None:
            reasons.append("rough_profit_unavailable")
        if reasons:
            excluded.append({"crop_id": crop_id, "missing_factors": reasons})
        else:
            rankable.append(candidate)

    profit_norm = _profit_scores(
        [float(item["rough_profit_bdt"]) for item in rankable]
    )
    scored: list[dict[str, Any]] = []
    for index, item in enumerate(rankable):
        soil = SUITABILITY_SCORE[item["soil_suitability_class"]]
        water = SUITABILITY_SCORE[item["water_class"]]
        profit_component = profit_norm.get(index, 0.0)
        composite = (
            WEIGHT_SOIL * soil
            + WEIGHT_WATER * water
            + WEIGHT_PROFIT * profit_component
        )
        risk = item.get("temperature_risk") or {}
        scored.append(
            {
                "crop_id": item["crop_id"],
                "composite_score": round(composite, 6),
                "soil_suitability_class": item["soil_suitability_class"],
                "water_class": item["water_class"],
                "rough_profit_bdt": round(float(item["rough_profit_bdt"]), 2),
                "risk_level": risk.get("level", "not_evaluated"),
                "risk_flags": risk.get("flags", []),
                "score_components": {
                    "soil": round(WEIGHT_SOIL * soil, 6),
                    "water": round(WEIGHT_WATER * water, 6),
                    "profit": round(WEIGHT_PROFIT * profit_component, 6),
                },
            }
        )

    # Deterministic order: composite desc, then profit desc, then crop_id asc.
    scored.sort(
        key=lambda row: (-row["composite_score"], -row["rough_profit_bdt"], row["crop_id"])
    )
    for position, row in enumerate(scored, start=1):
        row["rank"] = position

    if not scored:
        status = "no_rankable_crops"
    elif len(scored) < 3:
        status = "ranked_below_tier0_minimum_of_three"
    else:
        status = "ranked"

    return {
        "status": status,
        "policy": RANKING_POLICY,
        "ranked": scored,
        "excluded": excluded,
        "chosen_crop_id": scored[0]["crop_id"] if scored else None,
    }
