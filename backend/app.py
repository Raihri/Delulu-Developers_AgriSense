from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal
from uuid import uuid4

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

__version__ = "0.1.0"

from agent.controller import (
    PlanPreviewController,
    PlanPreviewDataError,
    PlanPreviewPersistenceError,
)
from agent.ranking_service import build_ranking
from agent.schemas import PlanPreviewRequest, PlanPreviewResponse
from agent.tracing import PlanTraceRecorder, weather_trace_output
from tools.season_plan import SeasonPlanDataError, build_season_plan
from config import (
    CURATED_ROOT,
    GeminiConfigurationError,
    GeminiSettings,
    PROJECT_ROOT,
    SupabaseConfigurationError,
    supabase_configured,
)
from db import get_database_client
from intake.parser import (
    GeminiExtractionError,
    GeminiIntakeExtractor,
    GeminiModelUnavailableError,
    GeminiRateLimitError,
    GeminiTransientError,
    IntakeLocation,
    build_intake_result,
)
from kb.vector_store import SupabaseVectorStore
from state.store import SupabaseStateStore
from tools.financials import project_financials
from tools.geo import resolve_location
from tools.recommend import assess_demo_crops
from tools.water_balance import (
    UnsupportedWaterModelError,
    calculate_water_balance,
)
from tools.weather import fetch_forecast


app = FastAPI(
    title="AgriSense AI",
    version=__version__,
    description="Source-grounded Bangladesh winter/dry-season demo API.",
)
logger = logging.getLogger(__name__)


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    """Serve the judge-facing page; it calls this API only, never Supabase directly."""
    return FileResponse(PROJECT_ROOT / "demo" / "index.html")


def require_supabase() -> Any:
    try:
        return get_database_client()
    except (SupabaseConfigurationError, ImportError) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Supabase is not configured. Set backend-only SUPABASE_DB_URL, "
                "or SUPABASE_URL plus SUPABASE_SECRET_KEY, after applying the migration."
            ),
        ) from exc


def require_gemini() -> GeminiIntakeExtractor | None:
    """Provide Gemini when configured; trusted location events do not require it."""
    try:
        return GeminiIntakeExtractor(GeminiSettings.from_environment())
    except GeminiConfigurationError:
        return None


def _table_rows(
    client: Any,
    table: str,
    *,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    try:
        query = client.table(table).select("*")
        for column, value in (filters or {}).items():
            query = query.eq(column, value)
        response = query.execute()
        return response.data or []
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Supabase query failed for {table}: {exc}"
        ) from exc


class GeoRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class WaterDay(BaseModel):
    etc_mm: float = Field(ge=0)
    rain_mm: float = Field(default=0, ge=0)
    irrigation_mm: float = Field(default=0, ge=0)
    runoff_mm: float | None = Field(default=None, ge=0)


class WaterRequest(BaseModel):
    days: list[WaterDay] = Field(min_length=1)
    taw_mm: float = Field(gt=0)
    depletion_fraction: float = Field(gt=0, le=1)
    starting_depletion_mm: float = Field(default=0, ge=0)
    irrigation_basis: Literal["net", "gross"] = "net"
    irrigation_efficiency: float | None = Field(default=None, gt=0, le=1)
    crop_id: str | None = None


class FinancialRequest(BaseModel):
    crop_id: Literal["boro_rice", "maize", "lentil", "wheat"]
    area_acres: float = Field(gt=0)
    allow_assumptions: bool = False
    overrides: dict[str, float] = Field(default_factory=dict)


class RankRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    soil_class: str = Field(min_length=1)
    drainage_condition: Literal["well_drained", "waterlogged"] | None = None
    water_availability: Literal[
        "irrigation_available", "surface_water_available", "rainfed", "limited"
    ] | None = None
    target_season: Literal["boro", "rabi", "kharif_1", "kharif_2"] = "rabi"
    area_acres: float = Field(default=1, gt=0)
    starting_depletion_mm: float | None = Field(default=None, ge=0)
    irrigation_mm_per_day: float | None = Field(default=None, ge=0)
    forecast_days: int = Field(default=16, ge=1, le=16)
    sowing_date: date | None = None
    variety_id: str | None = Field(default=None, min_length=1, max_length=80)
    soil_test_class: Literal["low", "medium", "high"] | None = None
    budget_bdt: float | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class ConversationPlanRequest(BaseModel):
    """Turn a completed intake conversation into a ranked, costed plan.

    The farm profile (soil, water, budget, season, size, sowing) is read from the
    intake session; live coordinates and the technical water inputs are supplied
    here because coordinates are never persisted and irrigation depth is not a
    conversational field.
    """

    session_id: str = Field(min_length=1, max_length=128)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    starting_depletion_mm: float | None = Field(default=None, ge=0)
    irrigation_mm_per_day: float | None = Field(default=None, ge=0)
    soil_test_class: Literal["low", "medium", "high"] | None = None
    forecast_days: int = Field(default=16, ge=1, le=16)


class RecommendationRequest(BaseModel):
    soil_class: str
    drainage_condition: Literal["well_drained", "waterlogged"] = "well_drained"
    area_acres: float = Field(default=1, gt=0)
    allow_assumptions: bool = False


class IntakeLocationRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source: Literal["live_location", "google_maps"]
    label: str | None = Field(default=None, max_length=180)


class IntakeChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    location: IntakeLocationRequest | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    event: Literal["message", "location_selected"] = "message"


@app.get("/health")
def health(client: Any = Depends(require_supabase)) -> dict[str, Any]:
    try:
        response = (
            client.table("build_metadata")
            .select("key,value")
            .in_(
                "key",
                [
                    "quality_status",
                    "source_registry_version",
                    "storage_backend",
                    "built_at",
                ],
            )
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase is configured but unavailable or not migrated: {exc}",
        ) from exc
    metadata = {row["key"]: row["value"] for row in response.data or []}
    return {
        "status": "ok" if metadata.get("quality_status") == "passed" else "not_seeded",
        "version": __version__,
        "storage_backend": "supabase_postgres_pgvector",
        "supabase_configured": supabase_configured(),
        "quality_status": metadata.get("quality_status"),
        "source_registry_version": metadata.get("source_registry_version"),
        "built_at": metadata.get("built_at"),
    }


@app.get("/sources/precedence")
def source_precedence() -> dict[str, Any]:
    return yaml.safe_load(
        (CURATED_ROOT / "source_precedence.yaml").read_text(encoding="utf-8")
    )


@app.post("/intake/chat")
def intake_chat(
    request: IntakeChatRequest,
    client: Any = Depends(require_supabase),
    extractor: GeminiIntakeExtractor | None = Depends(require_gemini),
) -> dict[str, Any]:
    """Turn explicit farmer language into reviewable plan inputs and cited context."""
    session_id = request.session_id or f"intake-{uuid4()}"
    store = SupabaseStateStore(client)
    existing_context: dict[str, Any] = {}
    clarification_state: dict[str, Any] = {}
    if request.session_id:
        try:
            state = store.load_session(request.session_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the intake context.",
            ) from exc
        if state is None:
            raise HTTPException(status_code=404, detail="Intake session was not found.")
        if state.get("schema_version") != "intake_context_v1":
            raise HTTPException(
                status_code=409,
                detail="The supplied session is not an intake session.",
            )
        stored_context = state.get("recognized")
        if isinstance(stored_context, dict):
            existing_context = stored_context
        stored_clarification = state.get("clarification_state")
        if isinstance(stored_clarification, dict):
            clarification_state = stored_clarification

    selected_location = (
        IntakeLocation(
            lat=request.location.lat,
            lon=request.location.lon,
            source=request.location.source,
            label=request.location.label,
        )
        if request.location
        else None
    )
    if request.event == "location_selected":
        if selected_location is None:
            raise HTTPException(
                status_code=422,
                detail="A trusted browser or map location is required.",
            )
        result = build_intake_result(
            {},
            request.message,
            location=selected_location,
            model=extractor.settings.model if extractor else "not_used",
            existing_context=existing_context,
            clarification_state=clarification_state,
        )
        result["mode"] = "trusted_location_update_v1"
    else:
        if extractor is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Gemini intake is not configured. Set backend-only "
                    "GEMINI_API_KEY and restart FastAPI."
                ),
            )
        try:
            result = extractor.extract(
                request.message,
                location=selected_location,
                existing_context=existing_context,
                clarification_state=clarification_state,
            )
        except GeminiRateLimitError as exc:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Gemini request limit is temporarily exhausted. "
                    "Your verified farm context is unchanged; wait a minute and retry."
                ),
            ) from exc
        except GeminiModelUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The configured Gemini model is unavailable. "
                    "Update backend GEMINI_MODEL to an available model and restart FastAPI."
                ),
            ) from exc
        except GeminiTransientError as exc:
            logger.warning("Gemini intake failed after retries: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Gemini is temporarily unavailable after three attempts. "
                    "Your verified farm context is unchanged; please retry shortly."
                ),
            ) from exc
        except GeminiExtractionError as exc:
            logger.warning("Gemini intake rejected a structured response: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=(
                    "Gemini could not safely extract this message. "
                    "Your verified farm context is unchanged; please rephrase and retry."
                ),
            ) from exc
    result["session_id"] = session_id
    persisted_context = {
        key: value
        for key, value in result["recognized"].items()
        if key
        not in {
            "location_text",
            "location_source",
            "location_label",
        }
    }
    try:
        store.save_session(
            session_id,
            {
                "schema_version": "intake_context_v1",
                "recognized": persisted_context,
                "missing": result["missing"],
                "next_field": result["next_field"],
                "clarification_state": result["clarification_state"],
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not save the verified intake context.",
        ) from exc

    retrieved = []
    if request.event == "message":
        crop_ids = result["recognized"]["crop_ids"]
        crop_filter = crop_ids[0] if len(crop_ids) == 1 else None
        try:
            retrieved = SupabaseVectorStore(client).search(
                request.message, crop=crop_filter, limit=3
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase retrieval failed during intake.",
            ) from exc
    return {
        **result,
        "retrieval": [
            {
                "chunk_id": item.chunk_id,
                "text": item.text,
                "score": round(item.score, 6),
                **item.metadata,
            }
            for item in retrieved
        ],
    }


@app.get("/kb/search")
def search_kb(
    q: str = Query(min_length=1),
    crop: str | None = None,
    topic: str | None = None,
    limit: int = Query(default=5, ge=1, le=20),
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    try:
        results = SupabaseVectorStore(client).search(
            q, limit=limit, crop=crop, topic=topic
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Supabase retrieval failed: {exc}") from exc
    return {
        "query": q,
        "retrieval_backend": "supabase_pgvector_deterministic_v1",
        "semantic_model_claimed": False,
        "results": [
            {
                "chunk_id": result.chunk_id,
                "score": round(result.score, 6),
                "text": result.text,
                **result.metadata,
            }
            for result in results
        ],
    }


@app.post("/geo/resolve")
def geo_resolve(request: GeoRequest) -> dict[str, Any]:
    return resolve_location(request.lat, request.lon)


@app.post("/water/balance")
def water_balance(request: WaterRequest) -> dict[str, Any]:
    try:
        return calculate_water_balance(
            [day.model_dump() for day in request.days],
            taw_mm=request.taw_mm,
            depletion_fraction=request.depletion_fraction,
            starting_depletion_mm=request.starting_depletion_mm,
            irrigation_basis=request.irrigation_basis,
            irrigation_efficiency=request.irrigation_efficiency,
            crop_id=request.crop_id,
        )
    except (ValueError, UnsupportedWaterModelError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/financials")
def financials(
    request: FinancialRequest,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    costs = _table_rows(
        client, "cost_baseline", filters={"crop_id": request.crop_id}
    )
    yields = _table_rows(
        client, "yield_baseline", filters={"crop_id": request.crop_id}
    )
    try:
        return project_financials(
            request.crop_id,
            request.area_acres,
            allow_assumptions=request.allow_assumptions,
            overrides=request.overrides,
            cost_rows=costs,
            yield_rows=yields,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/recommendations")
def recommendations(
    request: RecommendationRequest,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    soils = _table_rows(client, "crop_soil_suitability")
    calendars = _table_rows(client, "crop_calendar")
    costs = _table_rows(client, "cost_baseline") if request.allow_assumptions else None
    yields = _table_rows(client, "yield_baseline") if request.allow_assumptions else None
    return assess_demo_crops(
        soil_class=request.soil_class,
        drainage_condition=request.drainage_condition,
        area_acres=request.area_acres,
        allow_assumptions=request.allow_assumptions,
        soil_rows=soils,
        calendar_rows=calendars,
        cost_rows=costs,
        yield_rows=yields,
    )


@app.post("/plan/preview", response_model=PlanPreviewResponse)
def plan_preview(
    request: PlanPreviewRequest,
    client: Any = Depends(require_supabase),
) -> PlanPreviewResponse:
    """Return a partial, deterministic plan without adding a crop ranking."""

    try:
        return PlanPreviewController(client).preview(request)
    except PlanPreviewDataError as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not provide the reviewed plan-preview inputs.",
        ) from exc
    except PlanPreviewPersistenceError as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not save the plan preview and its evidence trace.",
        ) from exc


@app.post("/plan/rank")
def plan_rank(
    request: RankRequest,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Return a costed, weather-grounded ranking for one declared season.

    Ranking stays fail-closed: a crop is ordered only when its soil suitability,
    FAO-56 water class and rough profit are all available. Paddy rice remains
    unassessed. The response exposes the exact weather window, water totals and
    financial assumptions behind every ranked number.
    """
    session_id = request.session_id or f"rank-{uuid4()}"
    store = SupabaseStateStore(client)
    tracer = PlanTraceRecorder(store, session_id)
    # The session row must exist before its trace records (foreign key).
    store.save_session(
        session_id, {"schema_version": "plan_rank_v1", "status": "building"}
    )

    soil_rows = _table_rows(client, "crop_soil_suitability")
    calendars = _table_rows(client, "crop_calendar")
    crop_water_rows = _table_rows(client, "crop_water_stage")
    soil_water_rows = _table_rows(client, "soil_water_profile")
    cost_rows = _table_rows(client, "cost_baseline")
    yield_rows = _table_rows(client, "yield_baseline")
    tracer.record(
        step="load_reviewed_inputs",
        tool="supabase.structured_retrieval",
        params={"target_season": request.target_season},
        output={
            "tables": [
                "crop_soil_suitability",
                "crop_calendar",
                "crop_water_stage",
                "soil_water_profile",
                "cost_baseline",
                "yield_baseline",
            ],
            "soil_rows": len(soil_rows),
            "calendar_rows": len(calendars),
        },
        trace_type="structured_retrieval",
    )

    season_by_crop = {row["crop_id"]: row["season"] for row in calendars}
    crop_ids = [
        crop_id
        for crop_id in ("boro_rice", "maize", "lentil", "wheat")
        if season_by_crop.get(crop_id) == request.target_season
    ]

    weather_daily: dict[str, Any] | None = None
    weather_warning: str | None = None
    try:
        raw_weather = fetch_forecast(
            request.lat, request.lon, days=request.forecast_days
        )
        weather_daily = raw_weather.get("daily")
        tracer.record(
            step="fetch_weather",
            tool="weather.fetch_forecast",
            params={
                "forecast_days": request.forecast_days,
                "coordinate_precision": "withheld",
            },
            output=weather_trace_output(raw_weather),
            trace_type="external_api",
        )
    except Exception:
        weather_warning = (
            "Live Open-Meteo weather was unavailable; water class could not be "
            "computed and those crops are returned unassessed."
        )
        tracer.record(
            step="fetch_weather",
            tool="weather.fetch_forecast",
            params={"forecast_days": request.forecast_days},
            output={"error": "live weather unavailable"},
            trace_type="external_api",
            status="failure",
        )

    ranking = build_ranking(
        crop_ids=crop_ids,
        soil_class=request.soil_class,
        drainage_condition=request.drainage_condition,
        water_availability=request.water_availability,
        area_acres=request.area_acres,
        weather_daily=weather_daily,
        starting_depletion_mm=request.starting_depletion_mm,
        irrigation_mm_per_day=request.irrigation_mm_per_day,
        budget_bdt=request.budget_bdt,
        soil_rows=soil_rows,
        crop_water_rows=crop_water_rows,
        soil_water_rows=soil_water_rows,
        cost_rows=cost_rows,
        yield_rows=yield_rows,
    )

    # One computation trace per crop exposes the exact water-balance and
    # financial inputs behind each ranked number.
    for crop_id, detail in ranking["evidence"].items():
        tracer.record(
            step=f"water_balance:{crop_id}",
            tool="water_balance.calculate_water_balance",
            params={
                "crop_id": crop_id,
                "starting_depletion_mm": request.starting_depletion_mm,
                "irrigation_mm_per_day": request.irrigation_mm_per_day,
            },
            output={
                "water_detail": detail["water_detail"],
                "water_unassessed_reason": detail["water_unassessed_reason"],
                "total_cost_bdt": detail["total_cost_bdt"],
                "fits_budget": detail["fits_budget"],
            },
        )
    tracer.record(
        step="rank_candidates",
        tool="ranking.rank_candidates",
        params={"policy": ranking["policy"], "budget_bdt": ranking["budget_bdt"]},
        output={
            "status": ranking["status"],
            "chosen_crop_id": ranking["chosen_crop_id"],
            "ranked": [
                {
                    "rank": row["rank"],
                    "crop_id": row["crop_id"],
                    "composite_score": row["composite_score"],
                    "score_components": row["score_components"],
                    "soil_suitability_class": row["soil_suitability_class"],
                    "water_class": row["water_class"],
                    "rough_profit_bdt": row["rough_profit_bdt"],
                }
                for row in ranking["ranked"]
            ],
            "excluded": ranking["excluded"],
        },
    )

    chosen_plan: dict[str, Any] | None = None
    if ranking.get("chosen_crop_id"):
        try:
            chosen_plan = build_season_plan(
                client,
                ranking["chosen_crop_id"],
                sowing_date=request.sowing_date,
                variety_id=request.variety_id,
                soil_test_class=request.soil_test_class,
            )
        except (SeasonPlanDataError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not build the chosen-crop season plan: {exc}",
            ) from exc
        tracer.record(
            step=f"build_season_plan:{ranking['chosen_crop_id']}",
            tool="season_plan.build_season_plan",
            params={
                "crop_id": ranking["chosen_crop_id"],
                "sowing_date_supplied": request.sowing_date is not None,
                "soil_test_class": request.soil_test_class,
            },
            output={
                "status": chosen_plan["status"],
                "event_count": len(chosen_plan["events"]),
                "operations": sorted({e["operation"] for e in chosen_plan["events"]}),
            },
        )

        # Ground the chosen-crop advice in retrieved agronomic chunks. Below the
        # relevance threshold we return no prose advice rather than guessing.
        try:
            retrieved = SupabaseVectorStore(client).search(
                f"{ranking['chosen_crop_id']} fertilizer soil sowing calendar irrigation",
                crop=ranking["chosen_crop_id"],
                limit=3,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Supabase retrieval failed: {exc}"
            ) from exc
        threshold = 0.05
        grounded = [item for item in retrieved if item.score >= threshold]
        chosen_plan["grounding"] = {
            "retrieval_backend": "supabase_pgvector_deterministic_v1",
            "semantic_model_claimed": False,
            "relevance_threshold": threshold,
            "status": "grounded" if grounded else "below_relevance_threshold_no_prose_advice",
            "chunks": [
                {
                    "chunk_id": item.chunk_id,
                    "score": round(item.score, 6),
                    "text": item.text,
                    **item.metadata,
                }
                for item in grounded
            ],
        }
        tracer.record(
            step="rag_grounding",
            tool="vector_store.search",
            params={
                "crop": ranking["chosen_crop_id"],
                "relevance_threshold": threshold,
            },
            output={
                "status": chosen_plan["grounding"]["status"],
                "chunk_ids": [c["chunk_id"] for c in chosen_plan["grounding"]["chunks"]],
                "scores": [c["score"] for c in chosen_plan["grounding"]["chunks"]],
                "semantic_model_claimed": False,
            },
            trace_type="rag_retrieval",
        )

    response = {
        "session_id": session_id,
        "trace_ids": tracer.trace_ids,
        "target_season": request.target_season,
        "season_crop_ids": crop_ids,
        "weather_warning": weather_warning,
        "chosen_plan": chosen_plan,
        **ranking,
    }
    store.save_session(
        session_id,
        {
            "schema_version": "plan_rank_v1",
            "status": ranking["status"],
            "target_season": request.target_season,
            "chosen_crop_id": ranking["chosen_crop_id"],
            "trace_ids": tracer.trace_ids,
        },
    )
    return response


@app.post("/plan/from-conversation")
def plan_from_conversation(
    request: ConversationPlanRequest,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Single conversational path: intake session -> ranked, costed, dated plan.

    The collected farm profile is read from the intake session and fed straight
    into the ranking. If the conversation has not yet collected every minimum
    field, the plan fails closed and reports exactly what the farmer still owes.
    """
    try:
        state = SupabaseStateStore(client).load_session(request.session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Supabase could not load the intake session."
        ) from exc
    if state is None:
        raise HTTPException(status_code=404, detail="Intake session was not found.")
    if state.get("schema_version") != "intake_context_v1":
        raise HTTPException(
            status_code=409,
            detail="The supplied session is not a completed intake session.",
        )

    ctx = state.get("recognized") if isinstance(state.get("recognized"), dict) else {}
    required = {
        "soil_class": "soil type",
        "drainage_condition": "drainage condition",
        "water_availability": "water availability",
        "budget_bdt": "budget",
        "target_season": "target season",
        "area_acres": "farm size",
    }
    missing = [label for key, label in required.items() if ctx.get(key) in (None, "", [])]
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The conversation has not collected every field needed to plan.",
                "missing": missing,
            },
        )

    rank_request = RankRequest(
        lat=request.lat,
        lon=request.lon,
        soil_class=ctx["soil_class"],
        drainage_condition=ctx.get("drainage_condition"),
        water_availability=ctx.get("water_availability"),
        target_season=ctx.get("target_season"),
        area_acres=ctx.get("area_acres") or 1,
        starting_depletion_mm=request.starting_depletion_mm,
        irrigation_mm_per_day=request.irrigation_mm_per_day,
        forecast_days=request.forecast_days,
        sowing_date=ctx.get("sowing_date"),
        variety_id=ctx.get("variety_id"),
        soil_test_class=request.soil_test_class,
        budget_bdt=ctx.get("budget_bdt"),
        session_id=f"plan-from-{request.session_id}",
    )
    result = plan_rank(rank_request, client)
    result["from_conversation_session"] = request.session_id
    result["profile_used"] = {
        "soil_class": ctx.get("soil_class"),
        "drainage_condition": ctx.get("drainage_condition"),
        "water_availability": ctx.get("water_availability"),
        "target_season": ctx.get("target_season"),
        "area_acres": ctx.get("area_acres"),
        "budget_bdt": ctx.get("budget_bdt"),
        "sowing_date": ctx.get("sowing_date"),
    }
    return result


@app.get("/plan/preview/{session_id}")
def load_plan_preview(
    session_id: str,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Reload the compact, derived plan state by its opaque session identifier."""
    try:
        state = SupabaseStateStore(client).load_session(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Supabase could not load the saved preview.") from exc
    if state is None:
        raise HTTPException(status_code=404, detail="Saved plan preview was not found.")
    return state


@app.get("/plan/preview/{session_id}/traces")
def load_plan_traces(
    session_id: str,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Expose only the sanitized tool trace saved for a plan preview."""
    try:
        traces = SupabaseStateStore(client).list_traces(session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not load the saved plan trace.",
        ) from exc
    return {"session_id": session_id, "traces": traces}


@app.get("/weather/forecast")
def weather_forecast(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    days: int = Query(default=7, ge=1, le=16),
) -> dict[str, Any]:
    try:
        return fetch_forecast(lat, lon, days=days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Weather provider failed: {exc}") from exc
