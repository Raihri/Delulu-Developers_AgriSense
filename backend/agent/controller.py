from __future__ import annotations

from contextlib import nullcontext
from typing import Any
from uuid import uuid4

from agent.schemas import (
    MissingInput,
    PlanPreviewRequest,
    PlanPreviewResponse,
    UnassessedFactor,
)
from tools.geo import resolve_location
from tools.recommend import assess_demo_crops
from tools.season_plan import SeasonPlanDataError, build_season_plan
from state.store import SupabaseStateStore
from agent.tracing import (
    PlanTraceRecorder,
    financial_trace_output,
    geo_trace_output,
    recommendation_trace_output,
    retrieval_trace_output,
    season_trace_output,
    weather_trace_output,
)
from tools.weather import fetch_forecast


class PlanPreviewDataError(RuntimeError):
    """Raised when the controller cannot load its reviewed lookup slice."""


class PlanPreviewPersistenceError(RuntimeError):
    """Raised when a preview cannot be saved with its evidence trace."""


def _table_rows(client: Any, table: str) -> list[dict[str, Any]]:
    try:
        return client.table(table).select("*").execute().data or []
    except Exception as exc:
        raise PlanPreviewDataError(f"Could not load {table}") from exc


def _missing_inputs(
    request: PlanPreviewRequest,
    weather_snapshot: dict[str, Any] | None,
) -> list[MissingInput]:
    missing: list[MissingInput] = []
    if weather_snapshot is None:
        missing.append(
            MissingInput(
                field="weather_snapshot",
                reason="The live weather/ET0 service was unavailable.",
                needed_for=["daily water balance", "crop ranking"],
            )
        )
    if request.drainage_condition is None:
        missing.append(
            MissingInput(
                field="drainage_condition",
                reason="Drainage was not described and is no longer defaulted.",
                needed_for=["soil suitability"],
            )
        )
    if request.water_availability is None:
        missing.append(
            MissingInput(
                field="water_availability",
                reason="The farm water source was not supplied.",
                needed_for=["water suitability"],
            )
        )
    elif request.water_availability != "rainfed":
        missing.append(
            MissingInput(
                field="irrigation_plan",
                reason=(
                    "The water source is known, but irrigation quantity and "
                    "timing were not supplied."
                ),
                needed_for=["daily water balance", "crop ranking"],
            )
        )
    if request.soil_test_class is None:
        missing.append(
            MissingInput(
                field="soil_test_class",
                reason=(
                    "A broad soil texture is not a laboratory soil-test class; "
                    "no medium-fertility default was applied."
                ),
                needed_for=["fertilizer-rate selection"],
            )
        )
    if request.sowing_date is None:
        missing.append(
            MissingInput(
                field="sowing_date",
                reason="No sowing date was supplied for dated operation scheduling.",
                needed_for=["season-operation dates"],
            )
        )
    return missing


def _unassessed_factors(assessments: list[dict[str, Any]]) -> list[UnassessedFactor]:
    factors: list[UnassessedFactor] = []
    for assessment in assessments:
        crop_id = assessment["crop_id"]
        if assessment["soil_class"] == "unassessed":
            factors.append(
                UnassessedFactor(
                    crop_id=crop_id,
                    factor="soil_suitability",
                    status="unassessed",
                    reason="No reviewed suitability row matches this crop, soil class and drainage condition.",
                )
            )
        water_class = assessment["water_class"]
        if water_class.startswith("unassessed"):
            water_reasons = {
                "unassessed_paddy_model": (
                    "The paddy water model remains fail-closed until land "
                    "preparation, ponding, percolation and field-loss inputs are curated."
                ),
                "unassessed_soil_hydraulic_inputs": (
                    "Weather and rainfed status are available, but no matching "
                    "provisional crop and soil hydraulic profiles exist for this case."
                ),
                "unassessed_initial_soil_depletion": (
                    "Provisional CROPWAT crop and soil profiles are available, "
                    "but starting root-zone depletion is unknown and no local "
                    "calibration may be silently assumed."
                ),
                "unassessed_irrigation_schedule": (
                    "A water source is available, but irrigation quantity and timing are missing."
                ),
                "unassessed_water_source": "The farm water source is missing.",
            }
            factors.append(
                UnassessedFactor(
                    crop_id=crop_id,
                    factor="water_suitability",
                    status=water_class,
                    reason=water_reasons.get(
                        water_class, "The reviewed water inputs are incomplete."
                    ),
                )
            )
    return factors


def _financials(
    assessments: list[dict[str, Any]], *, allow_assumptions: bool
) -> dict[str, Any]:
    if not allow_assumptions:
        return {
            "status": "blocked_until_assumption_opt_in",
            "reason": "Costs and farmgate prices are editable demo assumptions.",
        }

    by_crop: list[dict[str, Any]] = []
    for assessment in assessments:
        financial = assessment.pop("rough_financials", None)
        if financial is not None:
            by_crop.append(financial)
    return {
        "status": "included_provisional_assumptions",
        "warning": "Costs and farmgate prices are project demo assumptions, not observed market data.",
        "by_crop": by_crop,
    }


def _season_events(plans: list[dict[str, Any]]) -> dict[str, Any]:
    events = [
        {"crop_id": plan["crop_id"], **event}
        for plan in plans
        for event in plan["events"]
    ]
    return {
        "status": "mixed" if any(plan["status"] == "mixed" for plan in plans) else "provisional",
        "events": events,
        "by_crop": plans,
    }


def _compact_state(response: PlanPreviewResponse) -> dict[str, Any]:
    """Keep reloadable derived results, never raw coordinates or source documents."""
    location = dict(response.location)
    location.pop("input", None)
    return {
        "schema_version": "plan_preview_v1",
        "session_id": response.session_id,
        "status": response.status,
        "location": location,
        "weather_snapshot": response.weather_snapshot,
        "assessments": response.assessments,
        "season_events": response.season_events,
        "financials": response.financials,
        "missing": [item.model_dump() for item in response.missing],
        "unassessed": [item.model_dump() for item in response.unassessed],
        "warnings": response.warnings,
        "trace_ids": response.trace_ids,
    }


class PlanPreviewController:
    """Compose existing deterministic tools without inventing a crop ranking."""

    def __init__(self, client: Any):
        self.client = client

    def preview(self, request: PlanPreviewRequest) -> PlanPreviewResponse:
        session = getattr(self.client, "session", None)
        context = session() if callable(session) else nullcontext()
        session_id = request.session_id or str(uuid4())
        store = SupabaseStateStore(self.client)
        tracer = PlanTraceRecorder(store, session_id)
        try:
            with context:
                # The parent must exist before its trace records because of the FK.
                store.save_session(
                    session_id,
                    {"schema_version": "plan_preview_v1", "status": "building"},
                )

                location = resolve_location(request.lat, request.lon)
                tracer.record(
                    step="resolve_location",
                    tool="geo.resolve_location",
                    params={"coordinate_precision": "withheld"},
                    output=geo_trace_output(location),
                )

                weather_snapshot: dict[str, Any] | None = None
                weather_warning: str | None = None
                try:
                    raw_weather = fetch_forecast(request.lat, request.lon, days=7)
                    weather_snapshot = {
                        key: value
                        for key, value in raw_weather.items()
                        if key not in {"request", "request_url"}
                    }
                    tracer.record(
                        step="fetch_weather",
                        tool="weather.fetch_forecast",
                        params={"forecast_days": 7, "coordinate_precision": "withheld"},
                        output=weather_trace_output(weather_snapshot),
                        trace_type="external_api",
                    )
                except Exception:
                    weather_warning = (
                        "Live Open-Meteo weather was unavailable; the preview "
                        "continued without inventing weather values."
                    )

                soil_rows = _table_rows(self.client, "crop_soil_suitability")
                calendars = _table_rows(self.client, "crop_calendar")
                crop_water_rows = _table_rows(self.client, "crop_water_stage")
                soil_water_rows = _table_rows(self.client, "soil_water_profile")
                tracer.record(
                    step="load_reviewed_inputs",
                    tool="supabase.structured_retrieval",
                    params={"crop_slice": ["boro_rice", "maize", "lentil", "wheat"]},
                    output=retrieval_trace_output(
                        soil_rows,
                        calendars,
                        crop_water_rows,
                        soil_water_rows,
                    ),
                    trace_type="structured_retrieval",
                )
                costs = (
                    _table_rows(self.client, "cost_baseline")
                    if request.allow_assumptions
                    else None
                )
                yields = (
                    _table_rows(self.client, "yield_baseline")
                    if request.allow_assumptions
                    else None
                )
                recommendation_result = assess_demo_crops(
                    soil_class=request.soil_class,
                    drainage_condition=request.drainage_condition,
                    water_availability=request.water_availability,
                    target_season=request.target_season,
                    crop_ids=list(request.crop_ids),
                    weather_available=weather_snapshot is not None,
                    area_acres=request.area_acres,
                    allow_assumptions=request.allow_assumptions,
                    soil_rows=soil_rows,
                    calendar_rows=calendars,
                    crop_water_rows=crop_water_rows,
                    soil_water_rows=soil_water_rows,
                    cost_rows=costs,
                    yield_rows=yields,
                )

                assessments = recommendation_result["candidates"]
                tracer.record(
                    step="assess_demo_crops",
                    tool="recommend.assess_demo_crops",
                    params={
                        "drainage_condition": request.drainage_condition,
                        "water_availability": request.water_availability,
                        "target_season": request.target_season,
                        "explicit_crop_ids": list(request.crop_ids),
                        "assumptions_explicitly_accepted": request.allow_assumptions,
                    },
                    output=recommendation_trace_output(assessments),
                )
                financials = _financials(
                    assessments, allow_assumptions=request.allow_assumptions
                )
                if request.allow_assumptions:
                    tracer.record(
                        step="project_financials",
                        tool="financials.project_financials",
                        params={"assumptions_explicitly_accepted": True},
                        output=financial_trace_output(financials),
                    )

                plans: list[dict[str, Any]] = []
                for crop_id in [
                    item["crop_id"] for item in assessments
                ]:
                    try:
                        plan = build_season_plan(
                            self.client,
                            crop_id,
                            sowing_date=request.sowing_date,
                            variety_id=request.variety_id,
                            soil_test_class=request.soil_test_class,
                        )
                    except (SeasonPlanDataError, ValueError) as exc:
                        raise PlanPreviewDataError("Could not build cited season plan") from exc
                    plans.append(plan)
                    tracer.record(
                        step=f"build_season_plan:{crop_id}",
                        tool="season_plan.build_season_plan",
                        params={
                            "crop_id": crop_id,
                            "sowing_date_supplied": request.sowing_date is not None,
                            "variety_supplied": request.variety_id is not None,
                            "soil_test_class": request.soil_test_class,
                        },
                        output=season_trace_output(plan),
                    )

                warnings = [recommendation_result["warning"]]
                if location.get("warning"):
                    warnings.append(location["warning"])
                if weather_warning:
                    warnings.append(weather_warning)
                response = PlanPreviewResponse(
                    status="partial",
                    session_id=session_id,
                    trace_ids=tracer.trace_ids,
                    location=location,
                    weather_snapshot=weather_snapshot,
                    assessments=assessments,
                    season_events=_season_events(plans),
                    financials=financials,
                    missing=_missing_inputs(request, weather_snapshot),
                    unassessed=_unassessed_factors(assessments),
                    warnings=warnings,
                )
                store.save_session(session_id, _compact_state(response))
                return response
        except PlanPreviewDataError:
            raise
        except Exception as exc:
            raise PlanPreviewPersistenceError(
                "Could not persist the plan preview and its safe trace."
            ) from exc
