from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanPreviewRequest(BaseModel):
    """Inputs for a deterministic, provenance-preserving plan preview."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    soil_class: str = Field(min_length=1)
    drainage_condition: Literal["well_drained", "waterlogged"] | None = None
    water_availability: Literal[
        "irrigation_available",
        "surface_water_available",
        "rainfed",
        "limited",
    ] | None = None
    target_season: Literal["boro", "rabi", "kharif_1", "kharif_2"] | None = None
    crop_ids: list[Literal["boro_rice", "maize", "lentil", "wheat"]] = Field(
        default_factory=list
    )
    area_acres: float = Field(default=1, gt=0)
    allow_assumptions: bool = False
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    sowing_date: date | None = None
    variety_id: str | None = Field(default=None, min_length=1, max_length=80)
    soil_test_class: Literal["low", "medium", "high"] | None = None


class MissingInput(BaseModel):
    field: str
    reason: str
    needed_for: list[str]


class UnassessedFactor(BaseModel):
    crop_id: str
    factor: str
    status: str
    reason: str


class PlanPreviewResponse(BaseModel):
    status: Literal["partial"]
    session_id: str
    trace_ids: list[str]
    location: dict[str, Any]
    weather_snapshot: dict[str, Any] | None
    assessments: list[dict[str, Any]]
    season_events: dict[str, Any]
    financials: dict[str, Any]
    missing: list[MissingInput]
    unassessed: list[UnassessedFactor]
    warnings: list[str]
