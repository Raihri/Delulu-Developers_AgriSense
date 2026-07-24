from __future__ import annotations

from typing import Any

from config import GeminiSettings
from intake.parser import GeminiIntakeExtractor


def extracted(
    value: Any = None,
    evidence: str | None = None,
    confidence: str = "none",
) -> dict[str, Any]:
    return {
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
    }


def empty_raw() -> dict[str, Any]:
    return {
        "location_text": extracted(),
        "farm_size_acres": extracted(),
        "soil_class": extracted(),
        "water_availability": extracted(),
        "budget_bdt": extracted(),
        "target_season": extracted(),
        "start_month": extracted(),
        "crop_ids": extracted([], None, "none"),
        "drainage_condition": extracted(),
        "sowing_date": extracted(),
        "variety_id": extracted(),
        "finance_requested": extracted(False, None, "none"),
        "latest_answer_status": "provided",
        "next_field": "farm_location",
        "follow_up_question": "খামারের সঠিক লোকেশন নির্বাচন করুন।",
    }


def fake_extractor(raw: dict[str, Any]) -> GeminiIntakeExtractor:
    return GeminiIntakeExtractor(
        GeminiSettings(api_key="test-key", model="test-gemini"),
        generate=lambda _prompt, _schema: raw,
    )
