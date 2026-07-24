from intake.parser import IntakeLocation
from tests.intake_fakes import empty_raw, extracted, fake_extractor


def test_gemini_extracts_complete_minimum_context_into_enums() -> None:
    conversation = (
        "রবি মৌসুমে আমার ১.৫ একর দোআঁশ জমিতে ভুট্টা লাগাবো, "
        "2026-10-01 এ বপন করব। সেচ আছে, বাজেট ৩০০০০ টাকা।"
    )
    raw = empty_raw()
    raw.update(
        {
            "farm_size_acres": extracted(1.5, "১.৫ একর", "high"),
            "soil_class": extracted("loam", "দোআঁশ", "high"),
            "drainage_condition": extracted(
                "well_drained", "দোআঁশ জমিতে", "medium"
            ),
            "water_availability": extracted(
                "irrigation_available", "সেচ আছে", "high"
            ),
            "budget_bdt": extracted(30_000, "বাজেট ৩০০০০ টাকা", "high"),
            "target_season": extracted("rabi", "রবি মৌসুমে", "high"),
            "crop_ids": extracted(["maize"], "ভুট্টা", "high"),
            "sowing_date": extracted("2026-10-01", "2026-10-01", "high"),
            "next_field": None,
            "follow_up_question": "প্রোফাইল সম্পূর্ণ।",
        }
    )
    result = fake_extractor(raw).extract(
        conversation,
        location=IntakeLocation(24.8, 89.3, "live_location"),
    )

    assert result["missing"] == []
    assert result["recognized"]["crop_ids"] == ["maize"]
    assert result["plan_input"]["soil_class"] == "loam"
    assert result["plan_input"]["area_acres"] == 1.5
    assert result["recognized"]["water_availability"] == "irrigation_available"
    assert result["recognized"]["budget_bdt"] == 30_000
    assert result["recognized"]["target_season"] == "rabi"
    assert result["plan_input"]["sowing_date"] == "2026-10-01"
    assert result["next_field"] is None
    assert result["mode"] == "gemini_structured_intake_v1"


def test_pond_language_maps_to_surface_water_without_enum_input() -> None:
    conversation = "I have a pond very close to the farm"
    raw = empty_raw()
    raw["water_availability"] = extracted(
        "surface_water_available", "pond very close", "medium"
    )

    result = fake_extractor(raw).extract(conversation)

    assert result["recognized"]["water_availability"] == (
        "surface_water_available"
    )
    water_trace = next(
        item
        for item in result["normalization_trace"]
        if item["field"] == "water_availability"
    )
    assert water_trace["evidence"] == "pond very close"
    assert water_trace["method"] == "gemini_structured_output"


def test_unsupported_model_value_is_rejected_instead_of_hallucinated() -> None:
    conversation = "My farm is one acre. I do not know the soil."
    raw = empty_raw()
    raw["farm_size_acres"] = extracted(1, "one acre", "high")
    raw["soil_class"] = extracted("loam", "loam", "high")

    result = fake_extractor(raw).extract(
        conversation,
        location=IntakeLocation(24.8, 89.3, "google_maps"),
    )

    assert result["recognized"]["soil_class"] is None
    assert "soil type" in result["missing"]


def test_low_confidence_ambiguous_enum_is_rejected_and_probed() -> None:
    conversation = "My farm is one acre with loam soil. Water comes sometimes."
    raw = empty_raw()
    raw.update(
        {
            "farm_size_acres": extracted(1, "one acre", "high"),
            "soil_class": extracted("loam", "loam soil", "high"),
            "drainage_condition": extracted(
                "well_drained", "Water comes sometimes", "medium"
            ),
            "water_availability": extracted(
                "limited", "Water comes sometimes", "low"
            ),
            "next_field": "water_availability",
            "follow_up_question": "Is irrigation reliable, limited, or rainfed?",
        }
    )

    result = fake_extractor(raw).extract(
        conversation,
        location=IntakeLocation(24.8, 89.3, "live_location"),
    )

    assert result["recognized"]["water_availability"] is None
    assert result["next_field"] == "water_availability"
    assert result["assistant_message"] == (
        "Is irrigation reliable, limited, or rainfed?"
    )


def test_text_location_never_becomes_invented_coordinates() -> None:
    conversation = "My farm is in Mymensingh"
    raw = empty_raw()
    raw["location_text"] = extracted(
        "Mymensingh", "Mymensingh", "high"
    )

    result = fake_extractor(raw).extract(conversation)

    assert result["recognized"]["location_text"] == "Mymensingh"
    assert result["plan_input"]["lat"] is None
    assert result["next_field"] == "farm_location"


def test_latest_uncertain_answer_does_not_erase_verified_context() -> None:
    first_message = (
        "My farm is one acre with loam soil. I have irrigation. "
        "My budget is 30000 taka."
    )
    first_raw = empty_raw()
    first_raw.update(
        {
            "farm_size_acres": extracted(1, "one acre", "high"),
            "soil_class": extracted("loam", "loam soil", "high"),
            "drainage_condition": extracted(
                "well_drained", "loam soil", "medium"
            ),
            "water_availability": extracted(
                "irrigation_available", "I have irrigation", "high"
            ),
            "budget_bdt": extracted(30_000, "budget is 30000 taka", "high"),
            "next_field": "target_season",
            "follow_up_question": "Which season are you planning for?",
        }
    )
    location = IntakeLocation(24.8, 89.3, "live_location")
    first = fake_extractor(first_raw).extract(first_message, location=location)

    uncertain_raw = empty_raw()
    uncertain_raw.update(
        {
            "latest_answer_status": "uncertain",
            "next_field": "target_season",
            "follow_up_question": "Is it Rabi, Boro, Kharif-1, or Kharif-2?",
        }
    )
    second = fake_extractor(uncertain_raw).extract(
        "I am not sure",
        location=location,
        existing_context=first["recognized"],
        clarification_state=first["clarification_state"],
    )

    assert second["recognized"]["budget_bdt"] == 30_000
    assert second["recognized"]["soil_class"] == "loam"
    assert second["recognized"]["water_availability"] == "irrigation_available"
    assert second["next_field"] == "target_season"
    assert second["assistant_message"] == (
        "কোন মাসে জমি প্রস্তুত, বপন বা রোপণ শুরু করতে চান?"
    )
    assert second["clarification_state"] == {
        "field": "target_season",
        "level": 1,
    }
    assert {option["id"] for option in second["answer_options"]} >= {
        "month_oct",
        "month_nov",
        "month_other",
    }


def test_reviewed_crop_and_start_month_resolve_season_without_guessing() -> None:
    raw = empty_raw()
    raw.update(
        {
            "start_month": extracted(11, "নভেম্বর", "high"),
            "next_field": "target_season",
            "follow_up_question": "কোন মৌসুম?",
        }
    )

    result = fake_extractor(raw).extract(
        "আমি নভেম্বর মাসে শুরু করতে চাই।",
        existing_context={
            "crop_ids": ["maize"],
            "area_acres": 1,
            "soil_class": "loam",
            "drainage_condition": "well_drained",
            "water_availability": "irrigation_available",
            "budget_bdt": 30_000,
        },
        clarification_state={"field": "target_season", "level": 1},
    )

    assert result["recognized"]["start_month"] == 11
    assert result["recognized"]["target_season"] == "rabi"
    assert result["next_field"] == "farm_location"
    season_trace = next(
        item
        for item in result["normalization_trace"]
        if item["field"] == "target_season"
    )
    assert season_trace["method"] == "reviewed_crop_calendar_resolution"
    assert "ais_crop_calendar" in season_trace["source"]


def test_month_without_crop_asks_crop_instead_of_guessing_season() -> None:
    raw = empty_raw()
    raw.update(
        {
            "start_month": extracted(11, "November", "high"),
            "next_field": "target_season",
            "follow_up_question": "Which season?",
        }
    )

    result = fake_extractor(raw).extract(
        "I want to start in November",
        location=IntakeLocation(24.8, 89.3, "live_location"),
        existing_context={
            "area_acres": 1,
            "soil_class": "loam",
            "drainage_condition": "well_drained",
            "water_availability": "irrigation_available",
            "budget_bdt": 30_000,
        },
        clarification_state={"field": "target_season", "level": 1},
    )

    assert result["recognized"]["start_month"] == 11
    assert result["recognized"]["target_season"] is None
    assert result["assistant_message"].startswith(
        "ওই মাস থেকে মৌসুম ঠিক করতে কোন ফসলটি"
    )
    assert result["clarification_state"] == {
        "field": "target_season",
        "level": 2,
    }
    assert {option["id"] for option in result["answer_options"]} == {
        "crop_boro",
        "crop_maize",
        "crop_lentil",
        "crop_other",
    }
