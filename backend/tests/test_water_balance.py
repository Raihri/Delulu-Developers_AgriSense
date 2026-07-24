from __future__ import annotations

import pytest

from tools.water_balance import (
    UnsupportedWaterModelError,
    calculate_water_balance,
)


def test_daily_balance_uses_retained_rain_and_reports_runoff_assumption() -> None:
    result = calculate_water_balance(
        [
            {"etc_mm": 5, "rain_mm": 3, "irrigation_mm": 0, "runoff_mm": 1},
            {"etc_mm": 5, "rain_mm": 0, "irrigation_mm": 4, "runoff_mm": None},
        ],
        taw_mm=100,
        depletion_fraction=0.5,
        starting_depletion_mm=20,
        crop_id="maize",
    )
    assert result["days"][0]["depletion_end_mm"] == 23
    assert result["days"][0]["effective_rain_mm"] == 2
    assert result["days"][1]["depletion_end_mm"] == 24
    assert result["assumptions"]["runoff_defaulted_to_zero"] is True
    assert result["water_class_policy"].startswith("provisional_project_policy")


def test_gross_irrigation_requires_explicit_efficiency() -> None:
    with pytest.raises(ValueError, match="explicit irrigation_efficiency"):
        calculate_water_balance(
            [{"etc_mm": 4, "irrigation_mm": 5}],
            taw_mm=50,
            depletion_fraction=0.5,
            irrigation_basis="gross",
        )
    result = calculate_water_balance(
        [{"etc_mm": 4, "irrigation_mm": 5}],
        taw_mm=50,
        depletion_fraction=0.5,
        irrigation_basis="gross",
        irrigation_efficiency=0.8,
    )
    assert result["totals"]["net_irrigation_mm"] == 4


def test_empty_series_is_rejected() -> None:
    with pytest.raises(ValueError, match="At least one"):
        calculate_water_balance([], taw_mm=50, depletion_fraction=0.5)


def test_paddy_water_score_fails_closed() -> None:
    with pytest.raises(UnsupportedWaterModelError, match="Paddy rice"):
        calculate_water_balance(
            [{"etc_mm": 4}],
            taw_mm=50,
            depletion_fraction=0.5,
            crop_id="boro_rice",
        )
