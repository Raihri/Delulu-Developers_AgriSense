from __future__ import annotations

from tools.advanced import (
    build_input_scheduler,
    build_pest_disease_risk,
    build_weather_watch,
    scenario_impacts,
)


def _weather() -> dict[str, object]:
    return {
        "time": ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18"],
        "temperature_2m_min": [20, 21, 20, 19],
        "temperature_2m_max": [30, 35, 31, 30],
        "precipitation_sum": [0, 27, 5, 3],
        "et0_fao_evapotranspiration": [3, 3, 3, 3],
    }


def test_weather_watch_adjusts_near_term_input_operation() -> None:
    result = build_weather_watch(
        _weather(),
        [
            {
                "operation": "fertilizer_application",
                "date": "2026-11-16",
                "timing": "Top dress",
            }
        ],
    )
    assert result["status"] == "triggered"
    assert {item["trigger"] for item in result["alerts"]} == {
        "heavy_rain_within_4_days",
        "heat_stress",
    }
    assert result["adjusted_events"][0]["original_date"] == "2026-11-16"
    assert result["adjusted_events"][0]["date"] == "2026-11-17"


def test_scheduler_converts_rates_and_exposes_costs_and_organic_options() -> None:
    scheduler = build_input_scheduler(
        chosen_plan={
            "crop_id": "wheat",
            "soil_test_class": "medium",
            "events": [
                {
                    "operation": "fertilizer_application",
                    "date_start": "2026-11-05",
                    "timing": "Basal",
                    "rates": [
                        {
                            "nutrient": "N",
                            "rate_min": 30,
                            "rate_max": 60,
                            "unit": "kg/ha",
                        },
                        {
                            "nutrient": "organic_fertilizer",
                            "rate_min": 2,
                            "rate_max": 2,
                            "unit": "t/ha",
                        },
                    ],
                    "source_id": "barc_frg_2024",
                    "source_locator": "PDF page 75",
                },
                {
                    "operation": "irrigation_checkpoint",
                    "date": "2026-12-01",
                    "stage": "development",
                    "timing": "Assess irrigation",
                    "source_id": "fao_cropwat",
                    "source_locator": "WHEAT.CRO",
                },
            ]
        },
        financials={
            "line_items": [
                {"item": "fertilizer_bundle", "total_cost_bdt": 7000},
                {"item": "irrigation", "total_cost_bdt": 3000},
            ]
        },
        area_acres=1,
        irrigation_mm_per_day=4,
    )
    assert scheduler["fertilizer"][0]["quantities"][0]["total_max_for_farm"] > 0
    assert scheduler["fertilizer"][0]["allocated_cost_bdt"] == 7000
    assert scheduler["irrigation"][0]["planned_net_depth_mm"] == 4
    assert scheduler["organic_alternatives"]
    assert scheduler["crop_id"] == "wheat"
    assert scheduler["soil_test_class"] == "medium"


def test_pest_risk_is_screening_only_and_never_prescribes_pesticide() -> None:
    result = build_pest_disease_risk(
        crop_id="wheat",
        weather_daily=_weather(),
        area_acres=1,
        chosen_plan={
            "sowing_date": "2026-11-01",
            "events": [
                {
                    "operation": "stage_start_development",
                    "date": "2026-11-12",
                },
                {"operation": "harvest", "date": "2027-03-01"},
            ],
        },
    )
    assert result["status"] == "screening_only_not_diagnosis"
    assert result["risks"]
    assert result["growth_stage"] == "development"
    assert all(item["growth_stage"] == "development" for item in result["risks"])
    assert "No pesticide or dosage" in result["pesticide_safety"]


def test_pest_risk_excludes_null_provider_values() -> None:
    weather = _weather()
    weather["temperature_2m_min"] = [20, 21, None, 19]
    weather["temperature_2m_max"] = [30, None, 31, 30]
    weather["precipitation_sum"] = [0, 27, None, 3]

    result = build_pest_disease_risk(
        crop_id="maize", weather_daily=weather, area_acres=1
    )

    coverage = result["risks"][0]["weather_basis"]["provider_value_coverage"]
    assert coverage == {
        "rain_values_used": 3,
        "rain_values_missing": 1,
        "temperature_values_used": 6,
        "temperature_values_missing": 2,
    }


def test_scenario_impacts_explain_rank_water_budget_and_profit() -> None:
    impacts = scenario_impacts(
        [
            {
                "crop_id": "lentil",
                "rank": 2,
                "water_class": "S1",
                "fits_budget": True,
                "rough_profit_bdt": 46_000,
            }
        ],
        [
            {
                "crop_id": "lentil",
                "rank": 1,
                "water_class": "S2",
                "fits_budget": False,
                "rough_profit_bdt": 44_000,
            }
        ],
    )

    assert impacts[0]["headline"] == "Moves up from #2 to #1."
    assert impacts[0]["attention"] == "budget"
    assert "No longer fits" in " ".join(impacts[0]["messages"])
    assert "S1 to S2" in " ".join(impacts[0]["messages"])
