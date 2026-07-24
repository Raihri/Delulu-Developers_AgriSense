from __future__ import annotations

import csv
import json
import math
import re
import time
from dataclasses import dataclass
from functools import cache
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import CURATED_ROOT, GeminiSettings
from intake.enums import (
    DrainageCondition,
    SoilClass,
    TargetSeason,
    WaterAvailability,
)


@dataclass(frozen=True)
class IntakeLocation:
    lat: float
    lon: float
    source: str
    label: str | None = None


class GeminiExtractionError(RuntimeError):
    """Raised when Gemini cannot return a valid structured intake result."""


class GeminiRateLimitError(GeminiExtractionError):
    """Raised when Gemini refuses intake because its request quota is exhausted."""


class GeminiModelUnavailableError(GeminiExtractionError):
    """Raised when the configured Gemini model is retired or unavailable."""


class GeminiTransientError(GeminiExtractionError):
    """Raised after retryable Gemini transport or response failures are exhausted."""


GenerateFunction = Callable[[str, dict[str, Any]], dict[str, Any]]

SOIL_VALUES = [item.value for item in SoilClass]
DRAINAGE_VALUES = [item.value for item in DrainageCondition]
WATER_VALUES = [item.value for item in WaterAvailability]
SEASON_VALUES = [item.value for item in TargetSeason]
CROP_VALUES = ["boro_rice", "maize", "lentil"]
NEXT_FIELDS = [
    "farm_location",
    "farm_size_acres",
    "soil_class",
    "drainage_condition",
    "water_availability",
    "budget_bdt",
    "target_season",
]
ANSWER_STATUSES = ["provided", "uncertain", "unrelated"]


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _field_schema(value_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "value": _nullable(value_schema),
            "evidence": _nullable(
                {
                    "type": "string",
                    "description": (
                        "An exact quote copied from the farmer conversation that "
                        "supports this value. Null when value is null."
                    ),
                }
            ),
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "none"],
            },
        },
        "required": ["value", "evidence", "confidence"],
    }


INTAKE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "location_text": _field_schema({"type": "string"}),
        "farm_size_acres": _field_schema(
            {"type": "number", "minimum": 0.000001}
        ),
        "soil_class": _field_schema(
            {"type": "string", "enum": SOIL_VALUES}
        ),
        "water_availability": _field_schema(
            {"type": "string", "enum": WATER_VALUES}
        ),
        "budget_bdt": _field_schema(
            {"type": "number", "minimum": 0.000001}
        ),
        "target_season": _field_schema(
            {"type": "string", "enum": SEASON_VALUES}
        ),
        "start_month": _field_schema(
            {
                "type": "integer",
                "minimum": 1,
                "maximum": 12,
                "description": (
                    "The intended land-preparation, sowing or transplanting "
                    "start month, normalized to 1-12."
                ),
            }
        ),
        "crop_ids": _field_schema(
            {
                "type": "array",
                "items": {"type": "string", "enum": CROP_VALUES},
            }
        ),
        "drainage_condition": _field_schema(
            {"type": "string", "enum": DRAINAGE_VALUES}
        ),
        "sowing_date": _field_schema(
            {
                "type": "string",
                "format": "date",
                "description": "ISO date only when the farmer supplied a date.",
            }
        ),
        "variety_id": _field_schema({"type": "string"}),
        "finance_requested": _field_schema({"type": "boolean"}),
        "latest_answer_status": {
            "type": "string",
            "enum": ANSWER_STATUSES,
            "description": (
                "uncertain when the farmer says they do not know or are not "
                "sure; unrelated when the latest message does not answer the "
                "current question; otherwise provided."
            ),
        },
        "next_field": _nullable(
            {"type": "string", "enum": NEXT_FIELDS}
        ),
        "follow_up_question": {
            "type": "string",
            "description": (
                "One short, natural Bangla or English question for next_field. "
                "Do not list every missing field."
            ),
        },
    },
    "required": [
        "location_text",
        "farm_size_acres",
        "soil_class",
        "water_availability",
        "budget_bdt",
        "target_season",
        "start_month",
        "crop_ids",
        "drainage_condition",
        "sowing_date",
        "variety_id",
        "finance_requested",
        "latest_answer_status",
        "next_field",
        "follow_up_question",
    ],
}


SYSTEM_INSTRUCTION = """
You are the farm-intake extractor for AgriSense Bangladesh. Extract only facts
provided by the farmer in the conversation. Convert natural Bangla, Banglish or
English phrases into the allowed canonical enum values. The farmer never needs
to say an enum literal.

Examples of semantic classification (examples are guidance, never evidence):
- a nearby usable pond/canal/river can mean surface_water_available;
- a working pump/tube-well/irrigation connection can mean irrigation_available;
- dependence on rainfall can mean rainfed;
- scarce or unreliable irrigation can mean limited;
- sticky/heavy soil can mean clay; balanced crumbly soil can mean loam;
- winter or after Aman harvest can mean rabi.
- month names or numbers may be normalized to start_month, but a month alone
  must not be guessed into a season enum.

Anti-hallucination contract:
1. Preserve CURRENT VERIFIED CONTEXT. Extract only additions or explicit
   corrections from LATEST FARMER MESSAGE. Never erase a verified field merely
   because the latest answer omits it or says "not sure" about another field.
2. Use only the latest message for updates. Never use outside knowledge.
3. For every non-null update, copy an exact quote from the latest message into
   evidence.
4. If multiple enum values remain plausible, confidence is low and value is null.
5. Never invent coordinates, acreage, budget, soil, water, season, dates or crop.
6. A village/district name may be location_text, but it is not coordinates.
7. Ask exactly one short follow-up for the first unresolved minimum field after
   combining verified context with supported updates:
   precise farm location, farm size, soil class, drainage condition, water
   availability, budget, then target season.
8. When all minimum fields appear present, next_field is null and the question
   simply confirms that the profile is ready.
9. Set latest_answer_status to uncertain when the latest answer says "not sure",
   "don't know", জানি না, নিশ্চিত নই, or has the same meaning. Do not treat
   uncertainty as a field value.
""".strip()


SAFE_QUESTIONS = {
    "farm_location": "খামারের সঠিক জায়গাটি Live location বা Map দিয়ে নির্বাচন করুন।",
    "farm_size_acres": "জমির মোট আয়তন কত একর?",
    "soil_class": "মাটির ধরন কেমন—দোআঁশ, বেলে দোআঁশ, নাকি এঁটেল?",
    "drainage_condition": "বৃষ্টির পর জমিতে পানি জমে থাকে, নাকি দ্রুত নেমে যায়?",
    "water_availability": "সেচের পানির উৎস ও প্রাপ্যতা কেমন?",
    "budget_bdt": "এই মৌসুমে আনুমানিক বাজেট কত টাকা?",
    "target_season": "কোন মৌসুমের জন্য পরিকল্পনা চান?",
}

ANSWER_OPTIONS: dict[str, list[dict[str, str]]] = {
    "farm_location": [
        {"id": "location_live", "label": "◎ Live location", "action": "live_location"},
        {"id": "location_map", "label": "⌖ Choose on map", "action": "google_maps"},
    ],
    "farm_size_acres": [
        {"id": "area_half", "label": "½ acre", "action": "message", "message": "আমার জমি আধা একর।"},
        {"id": "area_one", "label": "1 acre", "action": "message", "message": "আমার জমি 1 একর।"},
        {"id": "area_two", "label": "2 acres", "action": "message", "message": "আমার জমি 2 একর।"},
        {"id": "area_custom", "label": "Other amount", "action": "custom", "message": "আমার জমি  একর।"},
    ],
    "soil_class": [
        {"id": "soil_loam", "label": "দোআঁশ / Loam", "action": "message", "message": "আমার মাটি দোআঁশ।"},
        {"id": "soil_sandy", "label": "বেলে দোআঁশ / Sandy loam", "action": "message", "message": "আমার মাটি বেলে দোআঁশ।"},
        {"id": "soil_clay", "label": "এঁটেল / Clay", "action": "message", "message": "আমার মাটি এঁটেল।"},
        {"id": "soil_custom", "label": "Describe it", "action": "custom", "message": "আমার মাটি দেখতে/ছুঁতে "},
    ],
    "drainage_condition": [
        {"id": "drain_good", "label": "পানি নেমে যায়", "action": "message", "message": "বৃষ্টির পর জমির পানি দ্রুত নেমে যায়।"},
        {"id": "drain_waterlogged", "label": "পানি জমে থাকে", "action": "message", "message": "বৃষ্টির পর জমিতে পানি জমে থাকে।"},
        {"id": "drain_unknown", "label": "নিশ্চিত নই", "action": "custom", "message": "জমির পানি নিষ্কাশন সম্পর্কে "},
    ],
    "water_availability": [
        {"id": "water_irrigation", "label": "সেচ আছে", "action": "message", "message": "আমার সেচের ব্যবস্থা আছে।"},
        {"id": "water_surface", "label": "পুকুর/খাল আছে", "action": "message", "message": "কাছে ব্যবহারযোগ্য পুকুর বা খালের পানি আছে।"},
        {"id": "water_rain", "label": "বৃষ্টিনির্ভর", "action": "message", "message": "জমি বৃষ্টির উপর নির্ভরশীল।"},
        {"id": "water_limited", "label": "পানি সীমিত", "action": "message", "message": "সেচের পানি অনিয়মিত ও সীমিত।"},
    ],
    "budget_bdt": [
        {"id": "budget_20", "label": "৳20,000", "action": "message", "message": "আমার বাজেট 20000 টাকা।"},
        {"id": "budget_30", "label": "৳30,000", "action": "message", "message": "আমার বাজেট 30000 টাকা।"},
        {"id": "budget_50", "label": "৳50,000", "action": "message", "message": "আমার বাজেট 50000 টাকা।"},
        {"id": "budget_custom", "label": "Enter amount", "action": "custom", "message": "আমার বাজেট  টাকা।"},
    ],
    "target_season": [
        {"id": "season_rabi", "label": "রবি / Rabi", "action": "message", "message": "আমি রবি মৌসুমের পরিকল্পনা চাই।"},
        {"id": "season_boro", "label": "বোরো / Boro", "action": "message", "message": "আমি বোরো মৌসুমের পরিকল্পনা চাই।"},
        {"id": "season_k1", "label": "খরিফ-১", "action": "message", "message": "আমি খরিফ ১ মৌসুমের পরিকল্পনা চাই।"},
        {"id": "season_k2", "label": "খরিফ-২", "action": "message", "message": "আমি খরিফ ২ মৌসুমের পরিকল্পনা চাই।"},
    ],
}

MONTH_QUESTION = "কোন মাসে জমি প্রস্তুত, বপন বা রোপণ শুরু করতে চান?"
MONTH_OPTIONS = [
    {"id": "month_oct", "label": "অক্টোবর", "action": "message", "message": "আমি অক্টোবর মাসে শুরু করতে চাই।"},
    {"id": "month_nov", "label": "নভেম্বর", "action": "message", "message": "আমি নভেম্বর মাসে শুরু করতে চাই।"},
    {"id": "month_dec", "label": "ডিসেম্বর", "action": "message", "message": "আমি ডিসেম্বর মাসে শুরু করতে চাই।"},
    {"id": "month_jan", "label": "জানুয়ারি", "action": "message", "message": "আমি জানুয়ারি মাসে শুরু করতে চাই।"},
    {"id": "month_feb", "label": "ফেব্রুয়ারি", "action": "message", "message": "আমি ফেব্রুয়ারি মাসে শুরু করতে চাই।"},
    {"id": "month_other", "label": "অন্য মাস", "action": "custom", "message": "আমি  মাসে শুরু করতে চাই।"},
]
CROP_CLARIFICATION_QUESTION = (
    "ওই মাস থেকে মৌসুম ঠিক করতে কোন ফসলটি ভাবছেন—বোরো ধান, ভুট্টা, নাকি মসুর?"
)
CROP_CLARIFICATION_OPTIONS = [
    {"id": "crop_boro", "label": "বোরো ধান", "action": "message", "message": "আমি বোরো ধান ভাবছি।"},
    {"id": "crop_maize", "label": "ভুট্টা", "action": "message", "message": "আমি ভুট্টা ভাবছি।"},
    {"id": "crop_lentil", "label": "মসুর", "action": "message", "message": "আমি মসুর ভাবছি।"},
    {"id": "crop_other", "label": "অন্য ফসল", "action": "custom", "message": "আমি  ফসল ভাবছি।"},
]


@cache
def _reviewed_calendar_rows() -> tuple[dict[str, str], ...]:
    """Load only human-reviewed demo crop windows used for season resolution."""
    with (CURATED_ROOT / "crop_calendar.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        return tuple(
            row
            for row in csv.DictReader(source)
            if row.get("curation_status") == "human_reviewed"
            and row.get("crop_id") in CROP_VALUES
            and row.get("season") in SEASON_VALUES
        )


def _month_in_window(month: int, start: int, end: int) -> bool:
    return start <= month <= end if start <= end else month >= start or month <= end


def _resolve_reviewed_season(
    crops: list[str], start_month: int | None
) -> tuple[str | None, str | None]:
    """Resolve only a unique crop/month match from the reviewed demo calendar."""
    if start_month is None or len(crops) != 1:
        return None, None
    matches = [
        row
        for row in _reviewed_calendar_rows()
        if row["crop_id"] == crops[0]
        and _month_in_window(
            start_month,
            int(row["sow_start_month"]),
            int(row["sow_end_month"]),
        )
    ]
    seasons = {row["season"] for row in matches}
    if len(seasons) != 1:
        return None, None
    row = matches[0]
    return seasons.pop(), (
        f'{row["source_id"]} — {row["source_locator"]}'
    )


def _normalize_quote(value: str) -> str:
    return " ".join(value.casefold().strip().strip("\"'“”‘’").split())


def _supported_value(
    raw: dict[str, Any],
    field: str,
    conversation: str,
    *,
    allowed: set[str] | None = None,
    numeric: bool = False,
    array: bool = False,
) -> tuple[Any, dict[str, str] | None]:
    item = raw.get(field)
    if not isinstance(item, dict):
        return None, None
    value = item.get("value")
    if value is None:
        return None, None
    evidence = item.get("evidence")
    confidence = item.get("confidence")
    if (
        not isinstance(evidence, str)
        or not evidence.strip()
        or confidence not in {"high", "medium"}
        or _normalize_quote(evidence) not in _normalize_quote(conversation)
    ):
        return None, None
    if numeric:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            return None, None
        value = float(value)
    elif array:
        if not isinstance(value, list):
            return None, None
        if allowed is not None and any(item not in allowed for item in value):
            return None, None
    elif allowed is not None and value not in allowed:
        return None, None
    return value, {
        "field": field,
        "canonical_value": json.dumps(value, ensure_ascii=False),
        "evidence": evidence,
        "method": "gemini_structured_output",
        "confidence": confidence,
    }


def build_intake_result(
    raw: dict[str, Any],
    latest_message: str,
    *,
    location: IntakeLocation | None,
    model: str,
    existing_context: dict[str, Any] | None = None,
    clarification_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge evidence-validated turn updates into verified server context."""
    existing = existing_context or {}
    trace: list[dict[str, str]] = []

    def accept(field: str, **kwargs: Any) -> Any:
        value, item_trace = _supported_value(
            raw, field, latest_message, **kwargs
        )
        if item_trace is not None:
            trace.append(item_trace)
        return value

    new_location_text = accept("location_text")
    new_area = accept("farm_size_acres", numeric=True)
    new_soil_class = accept("soil_class", allowed=set(SOIL_VALUES))
    new_water = accept("water_availability", allowed=set(WATER_VALUES))
    new_budget = accept("budget_bdt", numeric=True)
    new_season = accept("target_season", allowed=set(SEASON_VALUES))
    new_start_month = accept("start_month", numeric=True)
    if (
        new_start_month is not None
        and (
            not float(new_start_month).is_integer()
            or not 1 <= int(new_start_month) <= 12
        )
    ):
        new_start_month = None
        trace = [item for item in trace if item["field"] != "start_month"]
    elif new_start_month is not None:
        new_start_month = int(new_start_month)
    new_crops = accept("crop_ids", allowed=set(CROP_VALUES), array=True)
    new_drainage = accept(
        "drainage_condition", allowed=set(DRAINAGE_VALUES)
    )
    new_sowing_date = accept("sowing_date")
    if new_sowing_date is not None and not re.fullmatch(
        r"20\d{2}-\d{2}-\d{2}", str(new_sowing_date)
    ):
        new_sowing_date = None
        trace = [item for item in trace if item["field"] != "sowing_date"]
    new_variety = accept("variety_id")
    new_finance_requested = accept("finance_requested")

    location_text = new_location_text or existing.get("location_text")
    area = new_area if new_area is not None else existing.get("area_acres")
    soil_class = new_soil_class or existing.get("soil_class")
    water = new_water or existing.get("water_availability")
    budget = new_budget if new_budget is not None else existing.get("budget_bdt")
    season = new_season or existing.get("target_season")
    start_month = (
        new_start_month
        if new_start_month is not None
        else existing.get("start_month")
    )
    crops = (
        new_crops
        if new_crops is not None
        else list(existing.get("crop_ids") or [])
    )
    drainage = new_drainage or existing.get("drainage_condition")
    sowing_date = new_sowing_date or existing.get("sowing_date")
    variety = new_variety or existing.get("variety_id")
    finance_requested = (
        bool(new_finance_requested)
        if new_finance_requested is not None
        else bool(existing.get("finance_requested", False))
    )
    if season is None:
        season, calendar_source = _resolve_reviewed_season(crops, start_month)
        if season is not None:
            trace.append(
                {
                    "field": "target_season",
                    "canonical_value": season,
                    "evidence": (
                        f"crop={crops[0]}, start_month={start_month}"
                    ),
                    "method": "reviewed_crop_calendar_resolution",
                    "confidence": "medium",
                    "source": calendar_source or "",
                }
            )

    missing_keys: list[str] = []
    missing: list[str] = []
    for key, value, description in (
        ("farm_location", location, "farm location (choose live location or map)"),
        ("farm_size_acres", area, "farm size"),
        ("soil_class", soil_class, "soil type"),
        ("drainage_condition", drainage, "drainage condition"),
        ("water_availability", water, "water availability"),
        ("budget_bdt", budget, "budget"),
        ("target_season", season, "target season"),
    ):
        if value is None:
            missing_keys.append(key)
            missing.append(description)

    next_field = missing_keys[0] if missing_keys else None
    prior_clarification = clarification_state or {}
    clarification_level = (
        int(prior_clarification.get("level", 0))
        if prior_clarification.get("field") == next_field
        else 0
    )
    if (
        next_field == "target_season"
        and raw.get("latest_answer_status") == "uncertain"
    ):
        clarification_level = max(1, clarification_level + 1)
    if next_field == "target_season" and start_month is not None and season is None:
        clarification_level = max(2, clarification_level)

    model_next = raw.get("next_field")
    model_question = raw.get("follow_up_question")
    if next_field == "target_season" and clarification_level >= 2:
        assistant_message = CROP_CLARIFICATION_QUESTION
        answer_options = CROP_CLARIFICATION_OPTIONS
    elif next_field == "target_season" and clarification_level >= 1:
        assistant_message = MONTH_QUESTION
        answer_options = MONTH_OPTIONS
    elif (
        next_field is not None
        and model_next == next_field
        and isinstance(model_question, str)
        and 3 <= len(model_question.strip()) <= 180
    ):
        assistant_message = model_question.strip()
        answer_options = ANSWER_OPTIONS.get(next_field, [])
    elif next_field is not None:
        assistant_message = SAFE_QUESTIONS[next_field]
        answer_options = ANSWER_OPTIONS.get(next_field, [])
    else:
        assistant_message = "তথ্য সম্পূর্ণ হয়েছে। প্রোফাইলটি দেখে পরিকল্পনা তৈরি করুন।"
        answer_options = []

    next_clarification = (
        {"field": next_field, "level": clarification_level}
        if next_field is not None
        else None
    )

    recognized = {
        "location_text": location_text,
        "location_source": location.source if location else None,
        "location_label": location.label if location else location_text,
        "area_acres": area,
        "soil_class": soil_class,
        "water_availability": water,
        "budget_bdt": budget,
        "target_season": season,
        "start_month": start_month,
        "crop_ids": crops,
        "drainage_condition": drainage,
        "sowing_date": sowing_date,
        "variety_id": variety,
        "finance_requested": finance_requested,
    }
    facts = [
        f"{field.replace('_', ' ')}: {value}"
        for field, value in recognized.items()
        if value not in (None, False, [], "")
        and field not in {"location_source", "location_label"}
    ]
    return {
        "assistant_message": assistant_message,
        "next_field": next_field,
        "answer_options": answer_options,
        "clarification_state": next_clarification,
        "recognized": recognized,
        "plan_input": {
            "lat": location.lat if location else None,
            "lon": location.lon if location else None,
            "soil_class": soil_class,
            "drainage_condition": drainage,
            "area_acres": area,
            "water_availability": water,
            "budget_bdt": budget,
            "target_season": season,
            "sowing_date": sowing_date,
            "variety_id": variety,
            "soil_test_class": None,
            "crop_ids": crops,
            "allow_assumptions": False,
        },
        "missing": missing,
        "facts": facts,
        "normalization_trace": trace,
        "enum_contract": {
            "soil_class": SOIL_VALUES,
            "drainage_condition": DRAINAGE_VALUES,
            "water_availability": WATER_VALUES,
            "target_season": SEASON_VALUES,
            "crop_ids": CROP_VALUES,
        },
        "mode": "gemini_structured_intake_v1",
        "model": model,
    }


class GeminiIntakeExtractor:
    """Gemini structured extraction with evidence-checked, fail-closed output."""

    def __init__(
        self,
        settings: GeminiSettings,
        *,
        generate: GenerateFunction | None = None,
    ):
        self.settings = settings
        self.generate = generate or self._generate

    def extract(
        self,
        latest_message: str,
        *,
        location: IntakeLocation | None = None,
        existing_context: dict[str, Any] | None = None,
        clarification_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        location_context = (
            {
                "selected": True,
                "source": location.source,
                "label": location.label,
                "coordinates_supplied_by_client": True,
            }
            if location
            else {
                "selected": False,
                "coordinates_supplied_by_client": False,
            }
        )
        prompt = (
            "CURRENT VERIFIED CONTEXT (retain unless the latest message "
            "explicitly corrects it):\n"
            + json.dumps(existing_context or {}, ensure_ascii=False)
            + "\n\nCURRENT CLARIFICATION STAGE:\n"
            + json.dumps(clarification_state or {}, ensure_ascii=False)
            + "\n\nLATEST FARMER MESSAGE (extract updates only from this text):\n"
            + latest_message
            + "\n\nTRUSTED LOCATION CONTEXT (not model-inferred):\n"
            + json.dumps(location_context, ensure_ascii=False)
        )
        raw = self.generate(prompt, INTAKE_RESPONSE_SCHEMA)
        if not isinstance(raw, dict):
            raise GeminiExtractionError("Gemini returned a non-object intake result")
        return build_intake_result(
            raw,
            latest_message,
            location=location,
            model=self.settings.model,
            existing_context=existing_context,
            clarification_state=clarification_state,
        )

    def _generate(
        self,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        model = self.settings.model
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + model
            + ":generateContent"
        )
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.settings.api_key,
            },
            method="POST",
        )
        max_attempts = 3
        retryable_http_codes = {408, 500, 502, 503, 504}
        last_failure = "unknown transient failure"
        for attempt in range(max_attempts):
            try:
                with urlopen(request, timeout=20) as response:  # noqa: S310
                    body = json.load(response)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code == 429:
                    raise GeminiRateLimitError(
                        "Gemini request quota is temporarily exhausted."
                    ) from exc
                if exc.code == 404:
                    raise GeminiModelUnavailableError(
                        f"The configured Gemini model '{model}' is unavailable."
                    ) from exc
                if exc.code not in retryable_http_codes:
                    raise GeminiExtractionError(
                        f"Gemini API rejected structured intake ({exc.code}): {detail}"
                    ) from exc
                last_failure = f"Gemini HTTP {exc.code}"
                if attempt == max_attempts - 1:
                    raise GeminiTransientError(
                        f"{last_failure} after {max_attempts} attempts"
                    ) from exc
                time.sleep(1.5 * (2**attempt))
                continue
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_failure = type(exc).__name__
                if attempt == max_attempts - 1:
                    raise GeminiTransientError(
                        f"{last_failure} after {max_attempts} attempts"
                    ) from exc
                time.sleep(1.5 * (2**attempt))
                continue

            try:
                output_text = body["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(output_text)
                if not isinstance(parsed, dict):
                    raise TypeError("structured output was not an object")
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                last_failure = "invalid structured response"
                if attempt == max_attempts - 1:
                    raise GeminiTransientError(
                        f"{last_failure} after {max_attempts} attempts"
                    ) from exc
                time.sleep(1.5 * (2**attempt))
                continue
            return parsed
        raise GeminiTransientError(last_failure)
