from __future__ import annotations

import pytest

from kb.build import seed_supabase
from tools.season_plan import build_season_plan
from tests.fakes import FakeSupabaseClient


@pytest.fixture
def seeded_client() -> FakeSupabaseClient:
    client = FakeSupabaseClient()
    seed_supabase(client, validate=False)
    return client


@pytest.mark.parametrize(
    ("crop_id", "variety_id"),
    [
        ("boro_rice", "brri_dhan28"),
        ("maize", None),
        ("lentil", None),
    ],
)
def test_each_demo_crop_has_cited_provisional_calendar_windows(
    seeded_client: FakeSupabaseClient, crop_id: str, variety_id: str | None
) -> None:
    plan = build_season_plan(seeded_client, crop_id, variety_id=variety_id)

    assert plan["status"] == "provisional"
    assert plan["sowing_date"] is None
    assert {event["operation"] for event in plan["events"]} >= {
        "sowing_or_transplant_window",
        "harvest_window",
    }
    assert all(
        event["source_id"] and event["source_locator"] for event in plan["events"]
    )
    assert all(event["date"] is None for event in plan["events"])
    assert any(item["field"] == "sowing_date" for item in plan["missing"])


def test_maize_uses_only_explicit_das_ranges_when_sowing_date_is_known(
    seeded_client: FakeSupabaseClient,
) -> None:
    plan = build_season_plan(
        seeded_client,
        "maize",
        sowing_date="2026-10-01",
        soil_test_class="medium",
    )

    assert plan["status"] == "mixed"
    fertilizer_ranges = [
        (event["date_start"], event["date_end"])
        for event in plan["events"]
        if event["operation"] == "fertilizer_application"
        and event["status"] == "dated_range"
    ]
    assert ("2026-11-20", "2026-11-25") in fertilizer_ranges
    assert ("2026-12-20", "2026-12-25") in fertilizer_ranges
    assert ("2026-09-21", "2026-09-30") in fertilizer_ranges
    assert all(
        event["status"] == "dated_range"
        for event in plan["events"]
        if event["operation"] == "fertilizer_application"
    )
    fertilizer_dated = [
        event
        for event in plan["events"]
        if event["operation"] == "fertilizer_application"
        and event["status"] == "dated_range"
    ]
    assert all(event["source_id"] == "barc_frg_2024" for event in fertilizer_dated)
    assert all(event["source_locator"] == "PDF page 91" for event in fertilizer_dated)
    basal = next(
        event
        for event in plan["events"]
        if event["timing"] == "One-third basal nitrogen application."
    )
    assert basal["date"] is None
    assert (
        basal["date_status"]
        == "placed inside the disclosed final-land-preparation window"
    )
    assert basal["assumption"]

    # The dated timeline now spans land preparation through harvest.
    operations = {event["operation"] for event in plan["events"]}
    assert {
        "land_preparation",
        "sowing_or_transplant",
        "irrigation_checkpoint",
        "weed_checkpoint",
        "pest_checkpoint",
        "harvest",
    } <= operations
    harvest = next(e for e in plan["events"] if e["operation"] == "harvest")
    # Maize CROPWAT stage sum is 20+35+40+30 = 125 days after 2026-10-01.
    assert harvest["date"] == "2027-02-03"
    assert all(
        event["source_id"] and event["source_locator"] for event in plan["events"]
    )


def test_variety_specific_boro_fertilizer_is_left_missing_without_variety(
    seeded_client: FakeSupabaseClient,
) -> None:
    plan = build_season_plan(
        seeded_client, "boro_rice", soil_test_class="medium"
    )

    assert plan["fertilizer_status"] == "missing_inputs"
    assert not any(
        event["operation"] == "fertilizer_application" for event in plan["events"]
    )
    assert any(item["field"] == "variety_id" for item in plan["missing"])
