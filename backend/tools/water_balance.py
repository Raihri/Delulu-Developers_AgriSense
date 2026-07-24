from __future__ import annotations

from typing import Any, Iterable


class UnsupportedWaterModelError(ValueError):
    """Raised when the curated data cannot safely support a water score."""


def _water_class(stress_fraction: float) -> str:
    if stress_fraction <= 0.05:
        return "S1"
    if stress_fraction <= 0.15:
        return "S2"
    if stress_fraction <= 0.30:
        return "S3"
    return "N"


def calculate_water_balance(
    days: Iterable[dict[str, float | None]],
    *,
    taw_mm: float,
    depletion_fraction: float,
    starting_depletion_mm: float = 0.0,
    irrigation_basis: str = "net",
    irrigation_efficiency: float | None = None,
    crop_id: str | None = None,
) -> dict[str, Any]:
    """Apply the FAO-56 Rev.1 daily root-zone depletion balance.

    Rainfall is treated as root-zone effective only after explicit runoff and
    computed deep percolation. Irrigation is net infiltrated water unless the
    caller explicitly supplies gross values and an efficiency.
    """

    day_values = list(days)
    if not day_values:
        raise ValueError("At least one daily water record is required")
    if crop_id == "boro_rice":
        raise UnsupportedWaterModelError(
            "Paddy rice water suitability is unassessed: land preparation, ponding, "
            "percolation and field-loss inputs are not curated."
        )
    if taw_mm <= 0:
        raise ValueError("taw_mm must be positive")
    if not 0 < depletion_fraction <= 1:
        raise ValueError("depletion_fraction must be in (0, 1]")
    if not 0 <= starting_depletion_mm <= taw_mm:
        raise ValueError("starting_depletion_mm must be between 0 and TAW")
    if irrigation_basis not in {"net", "gross"}:
        raise ValueError("irrigation_basis must be 'net' or 'gross'")
    if irrigation_basis == "gross" and (
        irrigation_efficiency is None or not 0 < irrigation_efficiency <= 1
    ):
        raise ValueError(
            "Gross irrigation requires an explicit irrigation_efficiency in (0, 1]"
        )

    raw_mm = depletion_fraction * taw_mm
    depletion = starting_depletion_mm
    rows: list[dict[str, Any]] = []
    runoff_defaulted = False
    total_etc = total_rain = total_effective_rain = total_net_irrigation = 0.0
    stress_days = 0

    for index, raw_day in enumerate(day_values, start=1):
        etc = float(raw_day.get("etc_mm") or 0.0)
        rain = float(raw_day.get("rain_mm") or 0.0)
        supplied_irrigation = float(raw_day.get("irrigation_mm") or 0.0)
        runoff_value = raw_day.get("runoff_mm")
        if runoff_value is None:
            runoff = 0.0
            runoff_defaulted = True
        else:
            runoff = float(runoff_value)
        if min(etc, rain, supplied_irrigation, runoff) < 0:
            raise ValueError(f"Day {index} contains a negative water value")
        if runoff > rain:
            raise ValueError(f"Day {index} runoff cannot exceed rainfall")

        net_irrigation = supplied_irrigation
        if irrigation_basis == "gross":
            net_irrigation *= float(irrigation_efficiency)
        infiltrated_rain = rain - runoff
        depletion_before = depletion

        # FAO-56 Rev.1 Eq. 8.7 with capillary rise omitted (explicitly zero).
        provisional_depletion = (
            depletion_before - infiltrated_rain - net_irrigation + etc
        )
        deep_percolation = max(0.0, -provisional_depletion)
        depletion = min(taw_mm, max(0.0, provisional_depletion + deep_percolation))
        unmet_depletion = max(0.0, provisional_depletion - taw_mm)

        # Retained rain cannot exceed the root-zone storage deficit left after
        # same-day ET and net irrigation. This is reported, not a fixed percent.
        effective_rain = min(
            infiltrated_rain,
            max(0.0, depletion_before + etc - net_irrigation),
        )
        stressed = depletion > raw_mm or unmet_depletion > 0
        stress_days += int(stressed)
        total_etc += etc
        total_rain += rain
        total_effective_rain += effective_rain
        total_net_irrigation += net_irrigation
        rows.append(
            {
                "day": index,
                "depletion_start_mm": round(depletion_before, 4),
                "etc_mm": etc,
                "rain_mm": rain,
                "runoff_mm": runoff,
                "net_irrigation_mm": round(net_irrigation, 4),
                "effective_rain_mm": round(effective_rain, 4),
                "deep_percolation_mm": round(deep_percolation, 4),
                "depletion_end_mm": round(depletion, 4),
                "unmet_depletion_mm": round(unmet_depletion, 4),
                "stressed": stressed,
            }
        )

    day_count = len(rows)
    stress_fraction = stress_days / day_count if day_count else 0.0
    return {
        "method": "FAO-56 Rev.1 equation 8.7",
        "method_source": "fao_56",
        "method_locator": "PDF page 298, equation 8.7",
        "taw_mm": taw_mm,
        "raw_mm": raw_mm,
        "totals": {
            "etc_mm": round(total_etc, 4),
            "rain_mm": round(total_rain, 4),
            "effective_rain_mm": round(total_effective_rain, 4),
            "net_irrigation_mm": round(total_net_irrigation, 4),
        },
        "stress_days": stress_days,
        "stress_day_fraction": round(stress_fraction, 4),
        "water_class": _water_class(stress_fraction),
        "water_class_policy": "provisional_project_policy_v1 (not FAO; not locally calibrated)",
        "assumptions": {
            "capillary_rise_mm": 0.0,
            "irrigation_basis": irrigation_basis,
            "irrigation_efficiency": irrigation_efficiency,
            "runoff_defaulted_to_zero": runoff_defaulted,
        },
        "days": rows,
    }
