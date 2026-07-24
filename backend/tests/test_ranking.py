from __future__ import annotations

from tools.agro_score import (
    build_etc_series,
    kc_for_day,
    summarize_weather,
    temperature_risk,
    _stage_boundaries,
)
from tools.ranking import rank_candidates


def _daily() -> dict[str, object]:
    return {
        "time": ["2026-11-20", "2026-11-21", "2026-11-22"],
        "temperature_2m_min": [11.0, 9.0, 12.0],
        "temperature_2m_max": [27.0, 35.0, 28.0],
        "precipitation_sum": [0.0, 5.0, 0.0],
        "et0_fao_evapotranspiration": [3.0, 3.2, 2.8],
    }


def test_summarize_weather_reduces_to_used_values() -> None:
    summary = summarize_weather(_daily())
    assert summary["day_count"] == 3
    assert summary["date_start"] == "2026-11-20"
    assert summary["date_end"] == "2026-11-22"
    assert summary["tmin_min_c"] == 9.0
    assert summary["tmax_max_c"] == 35.0
    assert summary["rain_total_mm"] == 5.0
    assert summary["et0_total_mm"] == 9.0


def test_kc_interpolates_within_stage() -> None:
    stages = [
        {"stage": "initial", "stage_order": 1, "duration_days": 2, "kc_start": 0.3, "kc_end": 0.3},
        {"stage": "development", "stage_order": 2, "duration_days": 4, "kc_start": 0.3, "kc_end": 1.1},
    ]
    boundaries = _stage_boundaries(stages)
    assert kc_for_day(boundaries, 0) == 0.3
    # development spans days 2..5 inclusive (span 4); midpoint interpolation.
    assert round(kc_for_day(boundaries, 2), 4) == 0.3
    assert kc_for_day(boundaries, 5) == 1.1
    assert kc_for_day(boundaries, 99) is None


def test_build_etc_series_uses_real_et0_and_rain() -> None:
    stages = [
        {"stage": "initial", "stage_order": 1, "duration_days": 3, "kc_start": 0.5, "kc_end": 0.5},
    ]
    series = build_etc_series(stages, _daily())
    assert series[0]["etc_mm"] == round(0.5 * 3.0, 4)
    assert series[1]["rain_mm"] == 5.0


def test_temperature_risk_flags_cold_and_heat() -> None:
    risk = temperature_risk(summarize_weather(_daily()), "wheat")
    assert "heat_stress_risk_tmax_ge_34c" in risk["flags"]
    assert "cold_stress_risk_tmin_le_10c" in risk["flags"]
    assert risk["level"] == "elevated"
    assert risk["threshold_basis"] == "fao_56"


def test_rank_orders_by_composite_and_excludes_unassessed() -> None:
    result = rank_candidates(
        [
            {"crop_id": "maize", "soil_suitability_class": "S1", "water_class": "S1", "rough_profit_bdt": 90000},
            {"crop_id": "wheat", "soil_suitability_class": "S1", "water_class": "S2", "rough_profit_bdt": 40000},
            {"crop_id": "lentil", "soil_suitability_class": "S1", "water_class": "S1", "rough_profit_bdt": 60000},
            {"crop_id": "boro_rice", "soil_suitability_class": None, "water_class": None, "rough_profit_bdt": None},
        ]
    )
    assert result["status"] == "ranked"
    order = [row["crop_id"] for row in result["ranked"]]
    assert order[0] == "maize"  # S1 water + highest profit
    assert order[-1] == "wheat"  # S2 water pulls it below the S1-water crops
    assert result["chosen_crop_id"] == "maize"
    assert {row["rank"] for row in result["ranked"]} == {1, 2, 3}
    assert any(
        item["crop_id"] == "boro_rice"
        and "soil_suitability_unassessed" in item["missing_factors"]
        for item in result["excluded"]
    )


def test_rank_reports_below_minimum_when_fewer_than_three() -> None:
    result = rank_candidates(
        [
            {"crop_id": "maize", "soil_suitability_class": "S1", "water_class": "S1", "rough_profit_bdt": 90000},
            {"crop_id": "wheat", "soil_suitability_class": "S2", "water_class": "S2", "rough_profit_bdt": 40000},
        ]
    )
    assert result["status"] == "ranked_below_tier0_minimum_of_three"
    assert result["chosen_crop_id"] == "maize"
