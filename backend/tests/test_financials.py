from __future__ import annotations

import pytest

from tools.financials import project_financials


def test_assumptions_are_opt_in() -> None:
    with pytest.raises(ValueError, match="allow_assumptions=true"):
        project_financials("maize", 1)


def test_area_scales_cost_and_revenue_but_not_break_even() -> None:
    one = project_financials("maize", 1, allow_assumptions=True)
    two = project_financials("maize", 2, allow_assumptions=True)
    assert two["total_cost_bdt"] == pytest.approx(one["total_cost_bdt"] * 2)
    assert two["revenue_bdt"] == pytest.approx(one["revenue_bdt"] * 2)
    assert two["break_even_yield_kg_per_acre"] == one["break_even_yield_kg_per_acre"]
    assert one["editable_assumptions"] is True


def test_price_override_is_visible_and_changes_revenue() -> None:
    baseline = project_financials("lentil", 1, allow_assumptions=True)
    edited = project_financials(
        "lentil",
        1,
        allow_assumptions=True,
        overrides={"farmgate_sale_price_bdt_per_kg": 110},
    )
    assert edited["farmgate_sale_price_bdt_per_kg"] == 110
    assert edited["revenue_bdt"] > baseline["revenue_bdt"]


def test_negative_cost_override_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        project_financials(
            "lentil",
            1,
            allow_assumptions=True,
            overrides={"labor_cost_per_acre_bdt": -1},
        )


def test_all_editable_cost_items_update_the_final_cost_list() -> None:
    edited = project_financials(
        "lentil",
        2,
        allow_assumptions=True,
        overrides={
            "seed_cost_per_acre_bdt": 1000,
            "fertilizer_bundle_cost_per_acre_bdt": 2000,
            "labor_cost_per_acre_bdt": 3000,
            "irrigation_cost_per_acre_bdt": 4000,
            "other_cost_per_acre_bdt": 5000,
        },
    )
    by_item = {row["item"]: row for row in edited["line_items"]}
    assert by_item["seed"]["cost_per_acre_bdt"] == 1000
    assert by_item["fertilizer_bundle"]["cost_per_acre_bdt"] == 2000
    assert by_item["labor"]["total_cost_bdt"] == 6000
    assert by_item["irrigation"]["total_cost_bdt"] == 8000
    assert by_item["other"]["total_cost_bdt"] == 10000
    assert edited["total_cost_bdt"] == 30000
