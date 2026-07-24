from __future__ import annotations

import csv
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from typing import Any

from config import CURATED_ROOT


ACRES_PER_HECTARE = Decimal("2.4710538147")
MONEY = Decimal("0.01")


@lru_cache(maxsize=1)
def _cost_rows() -> list[dict[str, str]]:
    with (CURATED_ROOT / "cost_baseline.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _yield_rows() -> dict[str, dict[str, str]]:
    with (CURATED_ROOT / "yield_baseline.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        return {row["crop_id"]: row for row in csv.DictReader(handle)}


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def project_financials(
    crop_id: str,
    area_acres: float,
    *,
    allow_assumptions: bool = False,
    overrides: dict[str, float] | None = None,
    cost_rows: list[dict[str, Any]] | None = None,
    yield_rows: list[dict[str, Any]] | dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project a demo budget while refusing silent use of assumed prices."""

    if not allow_assumptions:
        raise ValueError(
            "Financial inputs are editable demo assumptions. Set "
            "allow_assumptions=true to use them."
        )
    if area_acres <= 0:
        raise ValueError("area_acres must be positive")
    available_costs = cost_rows if cost_rows is not None else _cost_rows()
    crop_rows = [row for row in available_costs if row["crop_id"] == crop_id]
    if yield_rows is None:
        yield_row = _yield_rows().get(crop_id)
    elif isinstance(yield_rows, dict):
        yield_row = yield_rows.get(crop_id)
    else:
        yield_row = next(
            (row for row in yield_rows if row["crop_id"] == crop_id), None
        )
    if not crop_rows or not yield_row:
        raise KeyError(f"No curated financial slice for crop_id={crop_id!r}")

    overrides = overrides or {}
    area = Decimal(str(area_acres))
    line_items: list[dict[str, Any]] = []
    per_acre_cost = Decimal("0")
    sale_price: Decimal | None = None
    for row in crop_rows:
        if row["item_type"] == "output":
            sale_price = Decimal(
                str(overrides.get("farmgate_sale_price_bdt_per_kg", row["unit_price_bdt"]))
            )
            continue
        default_cost = Decimal(row["cost_per_acre_bdt"])
        cost = Decimal(str(overrides.get(f"{row['item']}_cost_per_acre_bdt", default_cost)))
        if cost < 0:
            raise ValueError(f"{row['item']} cost cannot be negative")
        per_acre_cost += cost
        line_items.append(
            {
                "item": row["item"],
                "cost_per_acre_bdt": _money(cost),
                "total_cost_bdt": _money(cost * area),
                "assumed": True,
                "source_id": row["source_id"],
                "source_locator": row["source_locator"],
            }
        )
    if sale_price is None or sale_price <= 0:
        raise ValueError("A positive farmgate sale price is required")

    yield_t_ha = Decimal(
        str(overrides.get("yield_t_ha", yield_row["canonical_yield_t_ha"]))
    )
    if yield_t_ha < 0:
        raise ValueError("yield_t_ha cannot be negative")
    yield_kg_per_acre = yield_t_ha * Decimal("1000") / ACRES_PER_HECTARE
    total_cost = per_acre_cost * area
    revenue = yield_kg_per_acre * area * sale_price
    profit = revenue - total_cost
    roi_percent = (
        (profit / total_cost * Decimal("100")) if total_cost else Decimal("0")
    )
    break_even_yield = per_acre_cost / sale_price
    break_even_price = (
        per_acre_cost / yield_kg_per_acre if yield_kg_per_acre else None
    )

    return {
        "crop_id": crop_id,
        "area_acres": area_acres,
        "assumption_gate": "explicitly_accepted",
        "editable_assumptions": True,
        "yield": {
            "t_per_ha": float(yield_t_ha),
            "kg_per_acre": float(yield_kg_per_acre.quantize(Decimal("0.001"))),
            "source_id": yield_row["source_id"],
            "source_locator": yield_row["source_locator"],
        },
        "farmgate_sale_price_bdt_per_kg": float(sale_price),
        "line_items": line_items,
        "total_cost_bdt": _money(total_cost),
        "revenue_bdt": _money(revenue),
        "net_profit_bdt": _money(profit),
        "roi_percent": _money(roi_percent),
        "break_even_yield_kg_per_acre": float(
            break_even_yield.quantize(Decimal("0.001"))
        ),
        "break_even_price_bdt_per_kg": (
            _money(break_even_price) if break_even_price is not None else None
        ),
        "warning": "Costs and sale price are project demo assumptions, not observed market data.",
    }
