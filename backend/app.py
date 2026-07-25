from __future__ import annotations

import base64
import binascii
import logging
import os
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

__version__ = "0.1.0"

from agent.controller import (
    PlanPreviewController,
    PlanPreviewDataError,
    PlanPreviewPersistenceError,
)
from agent.ranking_service import build_ranking
from agent.advice import build_explanations
from agent.schemas import PlanPreviewRequest, PlanPreviewResponse
from agent.scenario_chat import GeminiScenarioAdvisor
from agent.tracing import PlanTraceRecorder, weather_trace_output
from tools.season_plan import SeasonPlanDataError, build_season_plan
from config import (
    CURATED_ROOT,
    GeminiConfigurationError,
    GeminiSettings,
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
from tools.plant_health import PlantHealthProviderError, diagnose_plant_image
from tools.advanced import (
    build_input_scheduler,
    build_pest_disease_risk,
    build_weather_watch,
    scenario_deltas,
    scenario_impacts,
)


app = FastAPI(
    title="AgriSense AI",
    version=__version__,
    description="Source-grounded Bangladesh winter/dry-season demo API.",
)
logger = logging.getLogger(__name__)


@app.get("/demo", include_in_schema=False)
def demo() -> RedirectResponse:
    """Send judges to the maintained conversational Next.js interface."""

    target = os.environ.get("AGRISENSE_FRONTEND_URL", "http://127.0.0.1:3000")
    return RedirectResponse(target.rstrip("/") + "/", status_code=307)


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


def require_scenario_advisor() -> GeminiScenarioAdvisor | None:
    """Provide the project-aware scenario advisor when Gemini is configured."""
    try:
        return GeminiScenarioAdvisor(GeminiSettings.from_environment())
    except GeminiConfigurationError:
        return None


def require_plant_health() -> GeminiSettings | None:
    """Keep Gemini credentials on FastAPI; browsers receive normalized results."""
    try:
        return GeminiSettings.from_environment()
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


class PlantHealthDiagnosisRequest(BaseModel):
    image_base64: str = Field(min_length=32, max_length=12_000_000)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    filename: str | None = Field(default=None, max_length=180)
    language: Literal["en", "bn"] = "en"
    symptom_notes: str | None = Field(default=None, max_length=1000)


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
    forecast_days: int = Field(default=7, ge=1, le=16)
    sowing_date: date | None = None
    variety_id: str | None = Field(default=None, min_length=1, max_length=80)
    soil_test_class: Literal["low", "medium", "high"] | None = None
    budget_bdt: float | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    allow_assumptions: bool = False
    financial_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)
    rainfall_adjustment_percent: float = Field(default=0, ge=-100, le=300)
    selected_crop_id: Literal["boro_rice", "maize", "lentil", "wheat"] | None = None
    require_farmer_selection: bool = False


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
    forecast_days: int = Field(default=7, ge=1, le=16)
    sowing_date: date | None = None
    variety_id: str | None = Field(default=None, min_length=1, max_length=80)
    allow_assumptions: bool = False
    financial_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)
    budget_bdt: float | None = Field(default=None, ge=0)
    farmer_id: UUID | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    remember_profile: bool = False
    selected_crop_id: Literal["boro_rice", "maize", "lentil", "wheat"] | None = None


class ScenarioRequest(BaseModel):
    base_session_id: str = Field(min_length=1, max_length=128)
    farmer_id: UUID | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    message: str | None = Field(default=None, min_length=1, max_length=600)
    rainfall_change_percent: float | None = Field(default=None, ge=-100, le=300)
    budget_change_percent: float | None = Field(default=None, ge=-100, le=300)


class FarmerProfileSessionRequest(BaseModel):
    action: Literal["create", "login", "guest"]
    farmer_id: UUID | None = None
    farm_name: str | None = Field(default=None, min_length=2, max_length=80)


class FarmerProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)


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
    event: Literal["message", "location_selected", "profile_restore"] = "message"
    farmer_id: UUID | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    remember_profile: bool = False


def _farmer_memory_v3(
    profile: dict[str, Any] | None,
    *,
    farm_name: str = "Saved farm",
) -> dict[str, Any]:
    """Normalize legacy or empty profiles to the documented bounded schema."""

    memory = dict(profile or {})
    identity = memory.get("identity")
    if not isinstance(identity, dict):
        identity = {
            "farm_name": farm_name,
            "created_at": datetime.now(UTC).isoformat(),
            "access_mode": "farm",
        }
    identity = {
        **identity,
        "access_mode": (
            identity.get("access_mode")
            if identity.get("access_mode") in {"farm", "guest"}
            else "farm"
        ),
    }
    return {
        **memory,
        "schema_version": "farmer_memory_v3",
        "identity": identity,
        "recognized": (
            memory["recognized"] if isinstance(memory.get("recognized"), dict) else {}
        ),
        "conversation_history": [
            item
            for item in memory.get("conversation_history") or []
            if isinstance(item, dict)
        ][-8:],
        "projects": [
            item for item in memory.get("projects") or [] if isinstance(item, dict)
        ][:10],
    }


def _put_project_in_memory(
    memory: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    projects = [
        item
        for item in memory.get("projects") or []
        if isinstance(item, dict)
        and item.get("project_id") != project.get("project_id")
    ]
    return {
        **memory,
        "projects": [project, *projects][:10],
    }


def _canonical_projects_for_memory(
    store: SupabaseStateStore,
    farmer_id: str,
    memory: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return canonical projects, promoting legacy profile-only rows once."""

    canonical = store.list_farm_projects(farmer_id)
    known_ids = {
        str(item.get("project_id"))
        for item in canonical
        if item.get("project_id")
    }
    identity = memory.get("identity") or {}
    for legacy in memory.get("projects") or []:
        if not isinstance(legacy, dict) or not legacy.get("project_id"):
            continue
        project_id = str(legacy["project_id"])
        if project_id in known_ids:
            continue
        plan_session_id = legacy.get("plan_session_id")
        normalized = {
            **legacy,
            "project_id": project_id,
            "name": str(legacy.get("name") or "Saved farm project")[:80],
            "status": (
                legacy.get("status")
                if legacy.get("status")
                in {"draft", "intake", "planning", "active", "archived"}
                else "active"
                if plan_session_id
                else "draft"
            ),
            "access_mode": (
                legacy.get("access_mode")
                if legacy.get("access_mode") in {"farm", "guest"}
                else identity.get("access_mode")
                if identity.get("access_mode") in {"farm", "guest"}
                else "farm"
            ),
            "intake_session_id": legacy.get("intake_session_id"),
            "plan_session_id": plan_session_id,
        }
        store.save_farm_project(farmer_id, normalized)
        known_ids.add(project_id)
    return store.list_farm_projects(farmer_id)


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


def _matches_image_signature(image: bytes, mime_type: str) -> bool:
    signatures = {
        "image/jpeg": image.startswith(b"\xff\xd8\xff"),
        "image/png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": image.startswith(b"RIFF") and image[8:12] == b"WEBP",
    }
    return signatures.get(mime_type, False)


@app.post("/plant-health/diagnose")
def diagnose_plant_health(
    request: PlantHealthDiagnosisRequest,
    settings: GeminiSettings | None = Depends(require_plant_health),
) -> dict[str, Any]:
    """Tier-2 image screening through the server-only Gemini API."""

    if settings is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Plant Health is not configured. Add the server-only "
                "GEMINI_API_KEY and restart FastAPI."
            ),
        )
    try:
        image = base64.b64decode(request.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="The uploaded image encoding is invalid.",
        ) from exc
    if len(image) > 8 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="The image is larger than the 8 MB limit.",
        )
    if len(image) < 32 or not _matches_image_signature(image, request.mime_type):
        raise HTTPException(
            status_code=415,
            detail="Upload a valid JPEG, PNG or WebP plant image.",
        )
    try:
        return diagnose_plant_image(
            image,
            mime_type=request.mime_type,
            language=request.language,
            symptom_notes=request.symptom_notes,
            settings=settings,
        )
    except PlantHealthProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
    active_project: dict[str, Any] | None = None
    if request.project_id is not None:
        if request.farmer_id is None:
            raise HTTPException(
                status_code=409,
                detail="The intake project requires its owning farm session.",
            )
        try:
            active_project = store.load_farm_project(
                str(request.farmer_id),
                request.project_id,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the intake project.",
            ) from exc
        if active_project is None:
            raise HTTPException(
                status_code=404,
                detail="The intake project does not belong to this farm session.",
            )
    existing_context: dict[str, Any] = {}
    clarification_state: dict[str, Any] = {}
    restored_memory = False
    conversation_history: list[dict[str, str]] = []
    farmer_memory: dict[str, Any] = {}
    if (
        request.event in {"message", "profile_restore"}
        and request.remember_profile
        and request.farmer_id
    ):
        try:
            memory = store.load_farmer_profile(str(request.farmer_id))
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the consented farmer memory.",
            ) from exc
        if isinstance(memory, dict):
            farmer_memory = memory
            remembered = farmer_memory.get("recognized")
            if request.event == "profile_restore" and isinstance(remembered, dict):
                existing_context = {
                    key: value
                    for key, value in remembered.items()
                    if value not in (None, "", [])
                }
                restored_memory = bool(existing_context)
            history = farmer_memory.get("conversation_history")
            if isinstance(history, list):
                conversation_history = [
                    item
                    for item in history
                    if isinstance(item, dict)
                    and item.get("role") in {"user", "assistant"}
                    and isinstance(item.get("content"), str)
                ][-8:]
    if request.event == "profile_restore" and not restored_memory:
        raise HTTPException(
            status_code=404,
            detail="No consented farmer profile is available to restore.",
        )
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
            existing_context.update(
                {
                    key: value
                    for key, value in stored_context.items()
                    if value not in (None, "", [])
                }
            )
        stored_clarification = state.get("clarification_state")
        if isinstance(stored_clarification, dict):
            clarification_state = stored_clarification

    remembered_location = farmer_memory.get("location")
    selected_location = (
        IntakeLocation(
            lat=request.location.lat,
            lon=request.location.lon,
            source=request.location.source,
            label=request.location.label,
        )
        if request.location
        else IntakeLocation(
            lat=float(remembered_location["lat"]),
            lon=float(remembered_location["lon"]),
            source=str(remembered_location.get("source") or "google_maps"),
            label=remembered_location.get("label"),
        )
        if (
            request.event == "profile_restore"
            and isinstance(remembered_location, dict)
            and isinstance(remembered_location.get("lat"), (int, float))
            and isinstance(remembered_location.get("lon"), (int, float))
        )
        else None
    )
    if request.event in {"location_selected", "profile_restore"}:
        if request.event == "location_selected" and selected_location is None:
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
        result["mode"] = (
            "trusted_location_update_v1"
            if request.event == "location_selected"
            else "consented_profile_restore_v1"
        )
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
                "farmer_id": str(request.farmer_id) if request.farmer_id else None,
                "project_id": request.project_id,
                "memory_consent": request.remember_profile,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not save the verified intake context.",
        ) from exc

    tracer = PlanTraceRecorder(store, session_id)
    intake_tool = {
        "message": "gemini.structured_intake",
        "location_selected": "browser.location_event",
        "profile_restore": "state.restore_farmer_profile",
    }[request.event]
    intake_trace_type = {
        "message": "llm",
        "location_selected": "trusted_user_input",
        "profile_restore": "memory_retrieval",
    }[request.event]
    tracer.record(
        step="extract_intake",
        tool=intake_tool,
        params={
            "event": request.event,
            "message_character_count": len(request.message),
            "model": result.get("model"),
            "memory_context_restored": restored_memory,
        },
        output={
            "recognized": result["recognized"],
            "missing": result["missing"],
            "next_field": result["next_field"],
            "facts": result["facts"],
        },
        trace_type=intake_trace_type,
    )

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
        tracer.record(
            step="intake_rag_retrieval",
            tool="vector_store.search",
            params={
                "crop": crop_filter,
                "limit": 3,
                "query_character_count": len(request.message),
            },
            output={
                "chunks": [
                    {
                        "chunk_id": item.chunk_id,
                        "text": item.text,
                        "score": round(item.score, 6),
                        **item.metadata,
                    }
                    for item in retrieved
                ]
            },
            trace_type="rag_retrieval",
        )

    if (
        request.event == "message"
        and request.remember_profile
        and request.farmer_id
    ):
        conversation_history.extend(
            [
                {"role": "user", "content": request.message[:500]},
                {
                    "role": "assistant",
                    "content": str(result["assistant_message"])[:500],
                },
            ]
        )
        try:
            remembered_context = farmer_memory.get("recognized")
            recognized_for_memory = (
                persisted_context
                if not result["missing"] or not remembered_context
                else remembered_context
                if isinstance(remembered_context, dict)
                else {}
            )
            updated_memory = {
                **_farmer_memory_v3(farmer_memory),
                "recognized": recognized_for_memory,
                "conversation_history": conversation_history[-8:],
                "last_intake_session_id": session_id,
            }
            if selected_location is not None:
                updated_memory["location"] = {
                    "lat": round(selected_location.lat, 6),
                    "lon": round(selected_location.lon, 6),
                    "source": selected_location.source,
                    "label": selected_location.label,
                }
            store.save_farmer_profile(
                str(request.farmer_id),
                updated_memory,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not save the consented farmer memory.",
            ) from exc
    if active_project is not None and request.farmer_id is not None:
        now = datetime.now(UTC).isoformat()
        active_project.update(
            {
                "intake_session_id": session_id,
                "status": "intake",
                "recognized": persisted_context,
                "last_activity_at": now,
            }
        )
        if selected_location is not None:
            active_project["location"] = {
                "lat": round(selected_location.lat, 6),
                "lon": round(selected_location.lon, 6),
                "source": selected_location.source,
                "label": selected_location.label,
            }
        try:
            store.save_farm_project(str(request.farmer_id), active_project)
            latest_memory = _farmer_memory_v3(
                store.load_farmer_profile(str(request.farmer_id))
            )
            store.save_farmer_profile(
                str(request.farmer_id),
                _put_project_in_memory(latest_memory, active_project),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not save the intake inside this project.",
            ) from exc
    return {
        **result,
        "trace_ids": tracer.trace_ids,
        "memory": {
            "status": (
                "restored"
                if request.event == "profile_restore" and restored_memory
                else "saved"
                if (
                    request.event == "message"
                    and request.remember_profile
                    and request.farmer_id
                )
                else "unchanged"
                if request.remember_profile and request.farmer_id
                else "disabled"
            ),
            "farmer_id": str(request.farmer_id) if request.farmer_id else None,
            "conversation_history": conversation_history[-8:] if request.remember_profile else [],
        },
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


@app.post("/farmer/profile/session")
def open_farmer_profile_session(
    request: FarmerProfileSessionRequest,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Create or restore an opaque-ID farm profile session.

    The access ID is intentionally described as demo access, not password-grade
    authentication. Logging out is a client operation and never deletes memory.
    """

    store = SupabaseStateStore(client)
    if request.action == "login":
        if request.farmer_id is None:
            raise HTTPException(
                status_code=422,
                detail="Enter the Farm Access ID to log in.",
            )
        try:
            profile = store.load_farmer_profile(str(request.farmer_id))
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the farm profile.",
            ) from exc
        if not isinstance(profile, dict):
            raise HTTPException(
                status_code=404,
                detail="No saved farm matches this Farm Access ID.",
            )
        profile = _farmer_memory_v3(profile)
        try:
            profile["projects"] = _canonical_projects_for_memory(
                store,
                str(request.farmer_id),
                profile,
            )
            store.save_farmer_profile(str(request.farmer_id), profile)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not upgrade the farm profile memory.",
            ) from exc
        return {
            "farmer_id": str(request.farmer_id),
            "memory": profile,
            "session_mode": "restored",
            "authentication_boundary": "opaque_demo_access_id",
        }

    if request.action == "guest":
        farmer_id = uuid4()
        now = datetime.now(UTC).isoformat()
        profile = _farmer_memory_v3(
            {
                "identity": {
                    "farm_name": f"Guest farm {str(farmer_id)[:4].upper()}",
                    "created_at": now,
                    "access_mode": "guest",
                }
            },
        )
        try:
            store.save_farmer_profile(str(farmer_id), profile)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not create the guest farm session.",
            ) from exc
        return {
            "farmer_id": str(farmer_id),
            "memory": profile,
            "session_mode": "guest",
            "authentication_boundary": "non_resumable_guest_session",
        }

    farm_name = (request.farm_name or "").strip()
    if len(farm_name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Enter a farm name to create a profile.",
        )
    farmer_id = uuid4()
    now = datetime.now(UTC).isoformat()
    profile = _farmer_memory_v3(
        {
            "identity": {
                "farm_name": farm_name,
                "created_at": now,
                "access_mode": "farm",
            }
        },
    )
    try:
        store.save_farmer_profile(str(farmer_id), profile)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not create the farm profile.",
        ) from exc
    return {
        "farmer_id": str(farmer_id),
        "memory": profile,
        "session_mode": "created",
        "authentication_boundary": "opaque_demo_access_id",
    }


@app.get("/farmer/profile/{farmer_id}")
def load_farmer_profile(
    farmer_id: UUID,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Reload only a farmer-consented, bounded profile/conversation summary."""

    store = SupabaseStateStore(client)
    try:
        profile = store.load_farmer_profile(str(farmer_id))
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Supabase could not load farmer memory."
        ) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Farmer memory was not found.")
    profile = _farmer_memory_v3(profile)
    try:
        profile["projects"] = _canonical_projects_for_memory(
            store,
            str(farmer_id),
            profile,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Supabase could not load farm projects."
        ) from exc
    return {"farmer_id": str(farmer_id), "memory": profile}


@app.post("/farmer/profile/{farmer_id}/projects")
def create_farmer_project(
    farmer_id: UUID,
    request: FarmerProjectCreateRequest,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Create the database project required before opening the advisor."""

    store = SupabaseStateStore(client)
    try:
        profile = store.load_farmer_profile(str(farmer_id))
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Supabase could not load the farm session."
        ) from exc
    if not isinstance(profile, dict):
        raise HTTPException(status_code=404, detail="Farm session was not found.")
    project_name = request.name.strip()
    if len(project_name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Enter a project name with at least two visible characters.",
        )
    memory = _farmer_memory_v3(profile)
    now = datetime.now(UTC).isoformat()
    project = {
        "project_id": f"project-{uuid4()}",
        "farmer_id": str(farmer_id),
        "name": project_name,
        "status": "draft",
        "access_mode": (memory.get("identity") or {}).get("access_mode") or "farm",
        "intake_session_id": None,
        "plan_session_id": None,
        "crop_id": None,
        "created_at": now,
        "last_activity_at": now,
    }
    try:
        store.save_farm_project(str(farmer_id), project)
        memory = _put_project_in_memory(memory, project)
        store.save_farmer_profile(str(farmer_id), memory)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Supabase could not create the farm project."
        ) from exc
    return {"farmer_id": str(farmer_id), "project": project}


@app.get("/farmer/profile/{farmer_id}/projects")
def list_farmer_projects(
    farmer_id: UUID,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    store = SupabaseStateStore(client)
    try:
        profile = store.load_farmer_profile(str(farmer_id))
        projects = store.list_farm_projects(str(farmer_id))
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Supabase could not load farm projects."
        ) from exc
    if not isinstance(profile, dict):
        raise HTTPException(status_code=404, detail="Farm session was not found.")
    return {"farmer_id": str(farmer_id), "projects": projects}


@app.post("/farmer/profile/{farmer_id}/projects/{project_id}/refresh")
def refresh_farmer_project(
    farmer_id: UUID,
    project_id: str,
    client: Any = Depends(require_supabase),
) -> dict[str, Any]:
    """Refresh live weather advice for one consented, saved farm project."""

    store = SupabaseStateStore(client)
    try:
        profile = store.load_farmer_profile(str(farmer_id))
        project = store.load_farm_project(str(farmer_id), project_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not load the farmer projects.",
        ) from exc
    if not isinstance(profile, dict):
        raise HTTPException(status_code=404, detail="Farmer profile was not found.")
    if project is None:
        raise HTTPException(
            status_code=404,
            detail="The saved project does not belong to this farmer profile.",
        )
    plan_session_id = str(project.get("plan_session_id") or project_id)
    try:
        saved_plan = store.load_session(plan_session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Supabase could not load the saved project plan.",
        ) from exc
    if (
        not isinstance(saved_plan, dict)
        or saved_plan.get("schema_version") != "plan_rank_v1"
        or not isinstance(saved_plan.get("chosen_plan"), dict)
    ):
        raise HTTPException(
            status_code=409,
            detail="The project has no farmer-selected plan to monitor.",
        )
    project_location = project.get("location")
    if not isinstance(project_location, dict):
        raise HTTPException(
            status_code=409,
            detail="The project has no consented farm location for weather monitoring.",
        )
    try:
        lat = float(project_location["lat"])
        lon = float(project_location["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="The saved project location is invalid.",
        ) from exc
    snapshot = saved_plan.get("request_snapshot") or {}
    forecast_days = int(snapshot.get("forecast_days") or 7)
    try:
        raw_weather = fetch_forecast(lat, lon, days=forecast_days)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Live weather is unavailable; the saved project was not changed.",
        ) from exc
    weather_daily = raw_weather.get("daily")
    if not isinstance(weather_daily, dict):
        raise HTTPException(
            status_code=502,
            detail="The weather provider returned no usable daily forecast.",
        )
    chosen_plan = saved_plan["chosen_plan"]
    watch = build_weather_watch(weather_daily, chosen_plan.get("events") or [])
    pest_risk = build_pest_disease_risk(
        crop_id=str(saved_plan.get("chosen_crop_id")),
        weather_daily=weather_daily,
        area_acres=float(snapshot.get("area_acres") or 0),
        chosen_plan=chosen_plan,
    )
    checked_at = datetime.now(UTC).isoformat()
    advanced = dict(saved_plan.get("advanced") or {})
    advanced.update(
        {
            "weather_watch": watch,
            "pest_disease_risk": pest_risk,
            "project_monitor": {
                "status": "refreshed",
                "last_checked_at": checked_at,
                "source_id": raw_weather.get("source_id", "open_meteo"),
            },
        }
    )
    saved_plan["advanced"] = advanced
    saved_plan["weather_snapshot"] = {
        key: value
        for key, value in raw_weather.items()
        if key not in {"request", "request_url"}
    }
    tracer = PlanTraceRecorder(store, plan_session_id)
    refresh_trace_id = tracer.record(
        step="refresh_project_weather_advice",
        tool="advanced.refresh_saved_project",
        params={
            "project_id": project_id,
            "forecast_days": forecast_days,
        },
        output={
            "weather_watch": watch,
            "pest_disease_risk": pest_risk,
        },
        trace_type="proactive_weather_refresh",
    )
    saved_plan["trace_ids"] = [
        *[str(item) for item in saved_plan.get("trace_ids") or []],
        refresh_trace_id,
    ]
    store.save_session(plan_session_id, saved_plan)

    project.update(
        {
            "last_weather_check": checked_at,
            "weather_watch_status": watch.get("status"),
            "weather_alert_count": len(watch.get("alerts") or []),
            "adjusted_operation_count": len(watch.get("adjusted_events") or []),
        }
    )
    store.save_farm_project(str(farmer_id), project)
    profile = _put_project_in_memory(_farmer_memory_v3(profile), project)
    profile["last_plan_session_id"] = plan_session_id
    store.save_farmer_profile(str(farmer_id), profile)
    return {
        "farmer_id": str(farmer_id),
        "project": project,
        "plan": saved_plan,
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
    """Run one plan in a reused database session when the adapter supports it.

    The direct Postgres adapter otherwise reconnects for every lookup and trace
    insert, which can turn one plan into a minute-long request on a remote
    Supabase project. REST/fake adapters simply use their normal connection
    behavior.
    """

    return _execute_plan_rank(request, client)


def _execute_plan_rank(
    request: RankRequest,
    client: Any,
    *,
    weather_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_factory = getattr(client, "session", None)
    if callable(session_factory):
        with session_factory():
            return _plan_rank(
                request,
                client,
                weather_override=weather_override,
            )
    return _plan_rank(request, client, weather_override=weather_override)


def _plan_rank(
    request: RankRequest,
    client: Any,
    *,
    weather_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a costed, weather-grounded ranking for one declared season.

    Ranking stays fail-closed: a crop is ordered only when its soil suitability,
    FAO-56 water class and rough profit are all available. Paddy rice remains
    unassessed. The response exposes the exact weather window, water totals and
    financial assumptions behind every ranked number.
    """
    session_id = request.session_id or f"rank-{uuid4()}"
    if request.target_season == "rabi" and not request.allow_assumptions:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The Rabi ranking needs rough profit, so the farmer must "
                    "explicitly accept or edit the labelled demo financial assumptions."
                ),
                "missing": ["financial assumption consent"],
            },
        )
    store = SupabaseStateStore(client)
    tracer = PlanTraceRecorder(store, session_id)
    # The session row must exist before its trace records (foreign key).
    store.save_session(
        session_id, {"schema_version": "plan_rank_v1", "status": "building"}
    )
    location = resolve_location(request.lat, request.lon)
    tracer.record(
        step="resolve_location",
        tool="geo.resolve_location",
        params={
            "latitude": round(request.lat, 5),
            "longitude": round(request.lon, 5),
        },
        output=location,
        trace_type="geospatial_computation",
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
            "records": {
                "crop_soil_suitability": soil_rows,
                "crop_calendar": calendars,
                "crop_water_stage": crop_water_rows,
                "soil_water_profile": soil_water_rows,
                "cost_baseline": cost_rows,
                "yield_baseline": yield_rows,
            },
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
    weather_snapshot: dict[str, Any] | None = None
    weather_warning: str | None = None
    try:
        raw_weather = (
            weather_override
            if weather_override is not None
            else fetch_forecast(
                request.lat, request.lon, days=request.forecast_days
            )
        )
        provider_daily = raw_weather.get("daily")
        weather_snapshot = {
            key: value
            for key, value in raw_weather.items()
            if key not in {"request", "request_url"}
        }
        weather_daily = (
            {
                key: list(value) if isinstance(value, list) else value
                for key, value in provider_daily.items()
            }
            if isinstance(provider_daily, dict)
            else None
        )
        tracer.record(
            step="fetch_weather",
            tool=(
                "scenario.reuse_base_weather_snapshot"
                if weather_override is not None
                else "weather.fetch_forecast"
            ),
            params={
                "forecast_days": request.forecast_days,
                "latitude": round(request.lat, 5),
                "longitude": round(request.lon, 5),
            },
            output=weather_trace_output(raw_weather),
            trace_type=(
                "scenario_input"
                if weather_override is not None
                else "external_api"
            ),
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

    if weather_daily is not None and request.rainfall_adjustment_percent:
        original_rain = [
            float(value or 0)
            for value in weather_daily.get("precipitation_sum") or []
        ]
        multiplier = 1 + request.rainfall_adjustment_percent / 100
        adjusted_rain = [round(value * multiplier, 4) for value in original_rain]
        weather_daily["precipitation_sum"] = adjusted_rain
        tracer.record(
            step="apply_rainfall_scenario",
            tool="scenario.scale_rainfall",
            params={
                "rainfall_adjustment_percent": request.rainfall_adjustment_percent,
                "multiplier": multiplier,
            },
            output={
                "original_precipitation_sum": original_rain,
                "adjusted_precipitation_sum": adjusted_rain,
            },
            trace_type="scenario_computation",
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
        allow_assumptions=request.allow_assumptions,
        financial_overrides=request.financial_overrides,
        soil_rows=soil_rows,
        crop_water_rows=crop_water_rows,
        soil_water_rows=soil_water_rows,
        cost_rows=cost_rows,
        yield_rows=yield_rows,
    )
    recommended_crop_id = ranking.get("chosen_crop_id")
    ranked_crop_ids = [row["crop_id"] for row in ranking["ranked"]]
    if (
        request.selected_crop_id is not None
        and request.selected_crop_id not in ranked_crop_ids
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The farmer can only select a crop from the current ranking.",
                "selected_crop_id": request.selected_crop_id,
                "ranked_crop_ids": ranked_crop_ids,
            },
        )
    if request.selected_crop_id is not None:
        ranking["chosen_crop_id"] = request.selected_crop_id
        ranking["selection_source"] = "farmer"
    elif request.require_farmer_selection and recommended_crop_id is not None:
        ranking["chosen_crop_id"] = None
        ranking["selection_source"] = "awaiting_farmer"
        ranking["status"] = "awaiting_farmer_crop_selection"
    else:
        ranking["selection_source"] = (
            "agent_default" if recommended_crop_id is not None else "unavailable"
        )
    ranking["recommended_crop_id"] = recommended_crop_id

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
            },
        )
        if detail.get("financials") is not None:
            tracer.record(
                step=f"project_financials:{crop_id}",
                tool="financials.project_financials",
                params={
                    "crop_id": crop_id,
                    "area_acres": request.area_acres,
                    "overrides": request.financial_overrides.get(crop_id, {}),
                    "assumptions_explicitly_accepted": request.allow_assumptions,
                },
                output=detail["financials"],
                trace_type="financial_computation",
            )
    tracer.record(
        step="rank_candidates",
        tool="ranking.rank_candidates",
        params={"policy": ranking["policy"], "budget_bdt": ranking["budget_bdt"]},
        output={
            "status": ranking["status"],
            "recommended_crop_id": ranking["recommended_crop_id"],
            "chosen_crop_id": ranking["chosen_crop_id"],
            "selection_source": ranking["selection_source"],
            "ranked": ranking["ranked"],
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
        # Retrieve crop-specific evidence before rendering any farmer-facing
        # recommendation. Evidence for one crop is never reused to justify
        # another crop's rank.
        threshold = 0.05
        grounding_by_crop: dict[str, list[dict[str, Any]]] = {}
        vector_store = SupabaseVectorStore(client)
        for ranked_crop in ranking["ranked"]:
            crop_id = ranked_crop["crop_id"]
            try:
                retrieved = vector_store.search(
                    f"{crop_id} fertilizer soil sowing calendar irrigation",
                    crop=crop_id,
                    limit=3,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Supabase retrieval failed for {crop_id}: {exc}",
                ) from exc
            grounding_by_crop[crop_id] = [
                {
                    "chunk_id": item.chunk_id,
                    "score": round(item.score, 6),
                    "text": item.text,
                    **item.metadata,
                }
                for item in retrieved
                if item.score >= threshold
            ]
            tracer.record(
                step=f"rag_grounding:{crop_id}",
                tool="vector_store.search",
                params={
                    "crop": crop_id,
                    "query": (
                        f"{crop_id} fertilizer soil sowing calendar irrigation"
                    ),
                    "limit": 3,
                    "relevance_threshold": threshold,
                },
                output={
                    "status": (
                        "grounded"
                        if grounding_by_crop[crop_id]
                        else "below_relevance_threshold_no_prose_advice"
                    ),
                    "chunks": grounding_by_crop[crop_id],
                    "semantic_model_claimed": False,
                },
                trace_type="rag_retrieval",
            )
        grounded_chunks = grounding_by_crop[ranking["chosen_crop_id"]]
        chosen_plan["grounding"] = {
            "retrieval_backend": "supabase_pgvector_deterministic_v1",
            "semantic_model_claimed": False,
            "relevance_threshold": threshold,
            "status": (
                "grounded"
                if grounded_chunks
                else "below_relevance_threshold_no_prose_advice"
            ),
            "chunks": grounded_chunks,
        }

        profile = {
            "soil_class": request.soil_class,
            "drainage_condition": request.drainage_condition,
            "water_availability": request.water_availability,
            "target_season": request.target_season,
            "area_acres": request.area_acres,
            "budget_bdt": request.budget_bdt,
            "sowing_date": request.sowing_date.isoformat() if request.sowing_date else None,
            "soil_test_class": request.soil_test_class,
        }
        explanations = (
            build_explanations(
                profile=profile,
                ranking=ranking,
                chosen_plan=chosen_plan,
                grounding_by_crop=grounding_by_crop,
            )
            if any(grounding_by_crop.values())
            else []
        )
        explanation_trace_id = tracer.record(
            step="render_grounded_explanations",
            tool="advice.build_explanations",
            params={
                "profile": profile,
                "ranked_crop_ids": [row["crop_id"] for row in ranking["ranked"]],
                "grounding_chunk_ids_by_crop": {
                    crop_id: [row["chunk_id"] for row in chunks]
                    for crop_id, chunks in grounding_by_crop.items()
                },
            },
            output={"recommendations": explanations},
            trace_type="explanation",
        )
        for explanation in explanations:
            explanation["trace_ids"] = [explanation_trace_id]
        chosen_plan["recommendations"] = explanations

        chosen_evidence = ranking["evidence"][ranking["chosen_crop_id"]]
        advanced = {
            "persistent_memory": {
                "status": "available_with_farmer_consent",
                "farmer_id": None,
            },
            "weather_watch": build_weather_watch(
                weather_daily, chosen_plan.get("events", [])
            ),
            "input_scheduler": build_input_scheduler(
                chosen_plan=chosen_plan,
                financials=chosen_evidence.get("financials"),
                area_acres=request.area_acres,
                irrigation_mm_per_day=float(request.irrigation_mm_per_day or 0),
            ),
            "pest_disease_risk": build_pest_disease_risk(
                crop_id=ranking["chosen_crop_id"],
                weather_daily=weather_daily,
                area_acres=request.area_acres,
                chosen_plan=chosen_plan,
            ),
            "scenario_simulation": {
                "status": "available",
                "base_session_id": session_id,
                "endpoint": "/plan/scenario",
            },
        }
        tracer.record(
            step="build_advanced_advice",
            tool="advanced.build_tier1_features",
            params={
                "crop_id": ranking["chosen_crop_id"],
                "area_acres": request.area_acres,
            },
            output=advanced,
            trace_type="advanced_computation",
        )
        tracer.record(
            step=f"build_season_plan:{ranking['chosen_crop_id']}",
            tool="season_plan.build_season_plan",
            params={
                "crop_id": ranking["chosen_crop_id"],
                "sowing_date": request.sowing_date.isoformat() if request.sowing_date else None,
                "soil_test_class": request.soil_test_class,
            },
            output=chosen_plan,
            trace_type="season_plan",
        )
    else:
        explanations = []
        advanced = None

    response = {
        "session_id": session_id,
        "trace_ids": tracer.trace_ids,
        "location": location,
        "weather_snapshot": weather_snapshot,
        "target_season": request.target_season,
        "season_crop_ids": crop_ids,
        "weather_warning": weather_warning,
        "chosen_plan": chosen_plan,
        "explanations": explanations,
        "advanced": advanced,
        "financial_assumption_consent": request.allow_assumptions,
        "rainfall_adjustment_percent": request.rainfall_adjustment_percent,
        "assessments": [
            {
                "crop_id": row["crop_id"],
                "soil_class": row["soil_suitability_class"],
                "water_class": row["water_class"],
                "ranking_status": "ranked",
                "soil_evidence": ranking["evidence"][row["crop_id"]].get(
                    "soil_evidence"
                ),
            }
            for row in ranking["ranked"]
        ],
        "season_events": {
            "status": chosen_plan.get("status") if chosen_plan else "unavailable",
            "events": chosen_plan.get("events", []) if chosen_plan else [],
            "by_crop": [chosen_plan] if chosen_plan else [],
        },
        "financials": {
            "status": (
                "included_provisional_assumptions"
                if request.allow_assumptions
                else "blocked_until_assumption_opt_in"
            ),
            "warning": (
                "Costs and farmgate prices are project demo assumptions, not "
                "observed market data."
            ),
            "by_crop": [
                detail["financials"]
                for detail in ranking["evidence"].values()
                if detail.get("financials") is not None
            ],
        },
        "missing": [],
        "unassessed": ranking["excluded"],
        "warnings": [
            warning
            for warning in (
                weather_warning,
                location.get("warning"),
                ranking.get("weather_data_notice"),
                ranking.get("assumption_notice"),
            )
            if warning
        ],
        **ranking,
    }
    persisted_response = {
        **response,
        "schema_version": "plan_rank_v1",
        "request_snapshot": {
                "soil_class": request.soil_class,
                "drainage_condition": request.drainage_condition,
                "water_availability": request.water_availability,
                "target_season": request.target_season,
                "area_acres": request.area_acres,
                "starting_depletion_mm": request.starting_depletion_mm,
                "irrigation_mm_per_day": request.irrigation_mm_per_day,
                "forecast_days": request.forecast_days,
                "sowing_date": (
                    request.sowing_date.isoformat() if request.sowing_date else None
                ),
                "variety_id": request.variety_id,
                "soil_test_class": request.soil_test_class,
                "budget_bdt": request.budget_bdt,
                "allow_assumptions": request.allow_assumptions,
                "financial_overrides": request.financial_overrides,
                "selected_crop_id": request.selected_crop_id,
                "require_farmer_selection": request.require_farmer_selection,
            },
    }
    location_for_storage = dict(persisted_response["location"])
    location_for_storage.pop("input", None)
    persisted_response["location"] = location_for_storage
    store.save_session(session_id, persisted_response)
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
    active_project: dict[str, Any] | None = None
    if request.project_id is not None:
        if request.farmer_id is None or not request.remember_profile:
            raise HTTPException(
                status_code=409,
                detail="The plan project requires its owning farm session.",
            )
        try:
            active_project = SupabaseStateStore(client).load_farm_project(
                str(request.farmer_id),
                request.project_id,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the planning project.",
            ) from exc
        if active_project is None:
            raise HTTPException(
                status_code=404,
                detail="The planning project does not belong to this farm session.",
            )
        linked_intake = active_project.get("intake_session_id")
        if linked_intake not in (None, request.session_id):
            raise HTTPException(
                status_code=409,
                detail="This intake belongs to a different farm project.",
            )
        state_project_id = state.get("project_id")
        if state_project_id not in (None, request.project_id):
            raise HTTPException(
                status_code=409,
                detail="This intake session is linked to a different farm project.",
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
    effective_sowing_date = request.sowing_date or ctx.get("sowing_date")
    if effective_sowing_date in (None, ""):
        missing.append("sowing date")
    if request.soil_test_class is None:
        missing.append("laboratory soil-test class")
    if request.starting_depletion_mm is None:
        missing.append("starting soil-moisture depletion")
    if request.irrigation_mm_per_day is None:
        missing.append("planned irrigation depth")
    if not request.allow_assumptions:
        missing.append("financial assumption consent or edits")
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The conversation has not collected every field needed to plan.",
                "missing": missing,
            },
        )
    if ctx.get("target_season") != "rabi":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The complete three-crop path is currently curated for Rabi. "
                    "Choose Rabi for a Tier-0-complete plan."
                ),
                "supported_season": "rabi",
            },
        )

    effective_budget_bdt = (
        request.budget_bdt
        if request.budget_bdt is not None
        else ctx.get("budget_bdt")
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
        sowing_date=effective_sowing_date,
        variety_id=request.variety_id or ctx.get("variety_id"),
        soil_test_class=request.soil_test_class,
        budget_bdt=effective_budget_bdt,
        session_id=f"plan-from-{uuid4()}",
        allow_assumptions=request.allow_assumptions,
        financial_overrides=request.financial_overrides,
        selected_crop_id=request.selected_crop_id,
        require_farmer_selection=True,
    )
    result = plan_rank(rank_request, client)
    result["from_conversation_session"] = request.session_id
    result["profile_used"] = {
        "soil_class": ctx.get("soil_class"),
        "drainage_condition": ctx.get("drainage_condition"),
        "water_availability": ctx.get("water_availability"),
        "target_season": ctx.get("target_season"),
        "area_acres": ctx.get("area_acres"),
        "budget_bdt": effective_budget_bdt,
        "sowing_date": (
            effective_sowing_date.isoformat()
            if isinstance(effective_sowing_date, date)
            else effective_sowing_date
        ),
    }
    intake_traces = SupabaseStateStore(client).list_traces(request.session_id)
    result["intake_trace_session_id"] = request.session_id
    result["intake_trace_ids"] = [str(item["id"]) for item in intake_traces]
    if request.remember_profile and request.farmer_id:
        memory_store = SupabaseStateStore(client)
        remembered = _farmer_memory_v3(
            memory_store.load_farmer_profile(str(request.farmer_id))
        )
        remembered.update(
            {
                "schema_version": "farmer_memory_v3",
                "recognized": {
                    **(remembered.get("recognized") or {}),
                    **ctx,
                },
                "location": {
                    "lat": round(request.lat, 6),
                    "lon": round(request.lon, 6),
                    "source": "consented_plan_location",
                    "label": result.get("location", {})
                    .get("admin", {})
                    .get("adm3", {})
                    .get("name"),
                },
            }
        )
        remembered["last_plan_session_id"] = result["session_id"]
        remembered["last_plan_summary"] = {
            "chosen_crop_id": result.get("chosen_crop_id"),
            "target_season": result.get("target_season"),
            "budget_bdt": result.get("budget_bdt"),
            "status": result.get("status"),
        }
        now = datetime.now(UTC).isoformat()
        project = active_project or {
            "project_id": result["session_id"],
            "name": (
                f"{str(result.get('chosen_crop_id') or 'Farm plan').replace('_', ' ').title()} · "
                f"{result['profile_used'].get('sowing_date') or 'date pending'}"
            ),
            "access_mode": (
                (remembered.get("identity") or {}).get("access_mode") or "farm"
            ),
            "created_at": now,
        }
        project.update(
            {
                "farmer_id": str(request.farmer_id),
                "plan_session_id": result["session_id"],
                "intake_session_id": request.session_id,
                "status": (
                    "active" if result.get("chosen_crop_id") else "planning"
                ),
                "crop_id": result.get("chosen_crop_id"),
                "target_season": result.get("target_season"),
                "sowing_date": result["profile_used"].get("sowing_date"),
                "area_acres": result["profile_used"].get("area_acres"),
                "budget_bdt": result.get("budget_bdt"),
                "location": remembered["location"],
                "last_activity_at": now,
                "last_weather_check": (
                    now if result.get("chosen_crop_id") else None
                ),
                "weather_watch_status": (
                    (result.get("advanced") or {})
                    .get("weather_watch", {})
                    .get("status")
                    if result.get("chosen_crop_id")
                    else None
                ),
            }
        )
        remembered = _put_project_in_memory(remembered, project)
        memory_store.save_farm_project(str(request.farmer_id), project)
        result["farmer_project"] = project
        memory_store.save_farmer_profile(str(request.farmer_id), remembered)
        if isinstance(result.get("advanced"), dict):
            result["advanced"]["persistent_memory"] = {
                "status": (
                    "project_saved_across_sessions"
                    if result.get("farmer_project")
                    else "profile_saved_across_sessions"
                ),
                "farmer_id": str(request.farmer_id),
                "last_plan_session_id": result["session_id"],
                "project_count": len(remembered.get("projects") or []),
            }
    saved_plan = SupabaseStateStore(client).load_session(result["session_id"]) or {}
    result_project = result.get("farmer_project")
    saved_plan.update(
        {
            "project_id": (
                result_project.get("project_id")
                if isinstance(result_project, dict)
                else request.project_id
            ),
            "farmer_id": str(request.farmer_id) if request.farmer_id else None,
            "from_conversation_session": request.session_id,
            "profile_used": result["profile_used"],
            "intake_trace_session_id": request.session_id,
            "intake_trace_ids": result["intake_trace_ids"],
            "advanced": result.get("advanced"),
            "farmer_project": result.get("farmer_project"),
        }
    )
    SupabaseStateStore(client).save_session(result["session_id"], saved_plan)
    return result


def _bounded_scenario_history(value: Any) -> list[dict[str, Any]]:
    """Keep a compact, displayable project chat without internal identifiers."""
    if not isinstance(value, list):
        return []
    history: list[dict[str, Any]] = []
    for item in value[-20:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        row: dict[str, Any] = {
            "role": str(item["role"]),
            "content": content.strip()[:1200],
        }
        sections = item.get("context_sections")
        if isinstance(sections, list):
            row["context_sections"] = [str(section) for section in sections[:10]]
        history.append(row)
    return history[-20:]


def _scenario_project_context(
    base: dict[str, Any],
    *,
    profile: dict[str, Any] | None,
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expose all decision-relevant project learning without IDs or coordinates."""
    chosen_crop = str(base.get("chosen_crop_id") or "")
    evidence = base.get("evidence") if isinstance(base.get("evidence"), dict) else {}
    chosen_evidence = (
        evidence.get(chosen_crop)
        if chosen_crop and isinstance(evidence.get(chosen_crop), dict)
        else {}
    )
    advanced = base.get("advanced") if isinstance(base.get("advanced"), dict) else {}
    weather = (
        base.get("weather_snapshot")
        if isinstance(base.get("weather_snapshot"), dict)
        else {}
    )
    safe_project = {
        key: project.get(key)
        for key in (
            "name",
            "status",
            "crop_id",
            "target_season",
            "sowing_date",
            "area_acres",
            "budget_bdt",
            "last_weather_check",
            "weather_watch_status",
        )
        if isinstance(project, dict) and project.get(key) is not None
    }
    safe_snapshot = {
        key: value
        for key, value in (base.get("request_snapshot") or {}).items()
        if key not in {"lat", "lon", "session_id"}
    }
    safe_location = base.get("location") if isinstance(base.get("location"), dict) else {}
    return {
        "farm_profile": {
            "confirmed_facts": (
                profile.get("recognized")
                if isinstance(profile, dict) and isinstance(profile.get("recognized"), dict)
                else base.get("profile_used") or {}
            ),
            "location_context": {
                "admin": safe_location.get("admin"),
                "aez_candidates": safe_location.get("aez_candidates"),
            },
        },
        "project": {**safe_project, "planning_inputs": safe_snapshot},
        "crop_ranking": {
            "policy": base.get("policy"),
            "ranked": base.get("ranked") or [],
            "excluded": base.get("excluded") or [],
        },
        "selected_crop_plan": {
            "crop_id": chosen_crop,
            "selection_source": base.get("selection_source"),
            "plan": base.get("chosen_plan") or {},
            "explanations": base.get("explanations") or [],
        },
        "financial_projection": {
            "budget_bdt": base.get("budget_bdt"),
            "selected_crop_financials": chosen_evidence.get("financials"),
            "warning": (base.get("financials") or {}).get("warning")
            if isinstance(base.get("financials"), dict)
            else None,
        },
        "weather": {
            "source_id": weather.get("source_id"),
            "timezone": weather.get("timezone"),
            "daily_units": weather.get("daily_units"),
            "daily": weather.get("daily"),
            "watch": advanced.get("weather_watch"),
        },
        "input_schedule": advanced.get("input_scheduler"),
        "pest_screening": advanced.get("pest_disease_risk"),
        "evidence_and_limits": {
            "selected_crop_evidence": chosen_evidence,
            "warnings": base.get("warnings") or [],
            "missing": base.get("missing") or [],
            "unassessed": base.get("unassessed") or [],
        },
    }


@app.post("/plan/scenario")
def plan_scenario(
    request: ScenarioRequest,
    client: Any = Depends(require_supabase),
    advisor: GeminiScenarioAdvisor | None = Depends(require_scenario_advisor),
) -> dict[str, Any]:
    """Chat with the saved project and rerun audited numeric scenarios."""

    store = SupabaseStateStore(client)
    base = store.load_session(request.base_session_id)
    if base is None or base.get("schema_version") != "plan_rank_v1":
        raise HTTPException(
            status_code=404,
            detail="A ranked base-plan session is required for scenario simulation.",
        )
    scenario_project: dict[str, Any] | None = None
    scenario_profile: dict[str, Any] | None = None
    if request.project_id is not None:
        if request.farmer_id is None:
            raise HTTPException(
                status_code=409,
                detail="The scenario requires its owning farm session.",
            )
        try:
            scenario_project = store.load_farm_project(
                str(request.farmer_id),
                request.project_id,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the scenario project.",
            ) from exc
        if not isinstance(scenario_project, dict):
            raise HTTPException(
                status_code=404,
                detail="The scenario project does not belong to this farm session.",
            )
        try:
            loaded_profile = store.load_farmer_profile(str(request.farmer_id))
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase could not load the farm profile for scenario chat.",
            ) from exc
        if isinstance(loaded_profile, dict):
            scenario_profile = loaded_profile
    if not base.get("chosen_crop_id"):
        raise HTTPException(
            status_code=409,
            detail="The farmer must select a ranked crop before running scenarios.",
        )
    snapshot = base.get("request_snapshot")
    if not isinstance(snapshot, dict):
        raise HTTPException(
            status_code=409,
            detail="The saved plan predates scenario-ready request snapshots.",
        )
    base_weather = base.get("weather_snapshot")
    if (
        not isinstance(base_weather, dict)
        or not isinstance(base_weather.get("daily"), dict)
    ):
        raise HTTPException(
            status_code=409,
            detail="The saved plan has no weather snapshot for a controlled scenario.",
        )
    scenario_history = _bounded_scenario_history(
        base.get("scenario_chat_history")
        or (
            scenario_project.get("scenario_chat_history")
            if isinstance(scenario_project, dict)
            else []
        )
    )
    interpretation: dict[str, Any] | None = None
    if request.message is not None:
        if advisor is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Scenario chat needs Gemini. Configure GEMINI_API_KEY on the "
                    "FastAPI server."
                ),
            )
        try:
            interpretation = advisor.respond(
                request.message,
                project_context=_scenario_project_context(
                    base,
                    profile=scenario_profile,
                    project=scenario_project,
                ),
                history=scenario_history,
            )
        except GeminiRateLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except GeminiModelUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except GeminiTransientError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except GeminiExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if interpretation["intent"] != "simulate":
            scenario_history = _bounded_scenario_history(
                [
                    *scenario_history,
                    {"role": "user", "content": request.message},
                    {
                        "role": "assistant",
                        "content": interpretation["answer"],
                        "context_sections": interpretation["context_sections"],
                    },
                ]
            )
            chat_tracer = PlanTraceRecorder(store, request.base_session_id)
            trace_id = chat_tracer.record(
                step="answer_project_scenario_chat",
                tool="gemini.project_context_chat",
                params={"message": request.message[:600]},
                output={
                    "intent": interpretation["intent"],
                    "answer": interpretation["answer"],
                    "context_sections": interpretation["context_sections"],
                },
                trace_type="project_context_chat",
            )
            base["scenario_chat_history"] = scenario_history
            base["trace_ids"] = [
                *[str(item) for item in base.get("trace_ids") or []],
                trace_id,
            ]
            store.save_session(request.base_session_id, base)
            if scenario_project is not None and request.farmer_id is not None:
                scenario_project["scenario_chat_history"] = scenario_history
                scenario_project["last_activity_at"] = datetime.now(UTC).isoformat()
                store.save_farm_project(str(request.farmer_id), scenario_project)
                profile = _farmer_memory_v3(scenario_profile)
                store.save_farmer_profile(
                    str(request.farmer_id),
                    _put_project_in_memory(profile, scenario_project),
                )
            return {
                "schema_version": "scenario_chat_v1",
                "mode": interpretation["intent"],
                "assistant_message": interpretation["answer"],
                "context_used": interpretation["context_sections"],
                "scenario": None,
                "scenario_chat_history": scenario_history,
                "trace_ids": [trace_id],
            }

    rainfall_change_percent = (
        float(interpretation["rainfall_change_percent"] or 0)
        if interpretation is not None
        else float(request.rainfall_change_percent or 0)
    )
    budget_change_percent = (
        float(interpretation["budget_change_percent"] or 0)
        if interpretation is not None
        else float(request.budget_change_percent or 0)
    )
    original_budget = snapshot.get("budget_bdt")
    adjusted_budget = (
        round(float(original_budget) * (1 + budget_change_percent / 100), 2)
        if original_budget is not None
        else None
    )
    revised_params = {
        **snapshot,
        "lat": request.lat,
        "lon": request.lon,
        "budget_bdt": adjusted_budget,
        "rainfall_adjustment_percent": rainfall_change_percent,
        "session_id": f"scenario-{uuid4()}",
    }
    revised_request = RankRequest(**revised_params)
    revised = _execute_plan_rank(
        revised_request,
        client,
        weather_override=base_weather,
    )
    deltas = scenario_deltas(base.get("ranked") or [], revised.get("ranked") or [])
    impacts = scenario_impacts(
        base.get("ranked") or [],
        revised.get("ranked") or [],
    )
    top_before = (base.get("ranked") or [{}])[0].get("crop_id")
    top_after = (revised.get("ranked") or [{}])[0].get("crop_id")
    if top_before and top_after:
        summary = (
            f"{top_after.replace('_', ' ').title()} becomes the leading option "
            "under this scenario."
            if top_before != top_after
            else f"{top_after.replace('_', ' ').title()} remains the leading option "
            "under this scenario."
        )
    else:
        summary = "The scenario could not identify a complete leading option."
    scenario = {
        "base_session_id": request.base_session_id,
        "rainfall_change_percent": rainfall_change_percent,
        "budget_change_percent": budget_change_percent,
        "budget_before_bdt": original_budget,
        "budget_after_bdt": adjusted_budget,
        "summary": summary,
        "top_crop_before": top_before,
        "top_crop_after": top_after,
        "impacts": impacts,
        "deltas": deltas,
    }
    assistant_message: str | None = None
    context_used: list[str] = []
    if interpretation is not None and request.message is not None:
        changes = []
        if interpretation["rainfall_change_percent"] is not None:
            changes.append(
                f"rainfall {rainfall_change_percent:+g}%"
            )
        if interpretation["budget_change_percent"] is not None:
            changes.append(
                f"total budget {budget_change_percent:+g}%"
            )
        assistant_message = (
            f"I tested {' and '.join(changes)} against this saved project. "
            f"{summary} The comparison below shows what changes and what stays the same."
        )
        context_used = list(
            dict.fromkeys(
                [
                    *interpretation["context_sections"],
                    "crop_ranking",
                    "financial_projection",
                    "weather",
                ]
            )
        )
        scenario_history = _bounded_scenario_history(
            [
                *scenario_history,
                {"role": "user", "content": request.message},
                {
                    "role": "assistant",
                    "content": assistant_message,
                    "context_sections": context_used,
                },
            ]
        )
    scenario_tracer = PlanTraceRecorder(store, revised["session_id"])
    if interpretation is not None and request.message is not None:
        interpretation_trace_id = scenario_tracer.record(
            step="understand_project_scenario_chat",
            tool="gemini.project_context_chat",
            params={"message": request.message[:600]},
            output={
                "intent": interpretation["intent"],
                "rainfall_change_percent": interpretation[
                    "rainfall_change_percent"
                ],
                "budget_change_percent": interpretation["budget_change_percent"],
                "context_sections": interpretation["context_sections"],
            },
            trace_type="project_context_chat",
        )
        revised["trace_ids"].append(interpretation_trace_id)
    trace_id = scenario_tracer.record(
        step="compare_scenario",
        tool="advanced.scenario_deltas",
        params={
            "base_session_id": request.base_session_id,
            "rainfall_change_percent": rainfall_change_percent,
            "budget_change_percent": budget_change_percent,
        },
        output=scenario,
        trace_type="scenario_computation",
    )
    revised["trace_ids"].append(trace_id)
    revised["scenario"] = scenario
    if assistant_message is not None:
        revised["assistant_message"] = assistant_message
        revised["context_used"] = context_used
        revised["scenario_chat_history"] = scenario_history
    saved = store.load_session(revised["session_id"]) or {}
    saved["scenario"] = scenario
    saved["trace_ids"] = revised["trace_ids"]
    saved["project_id"] = request.project_id
    saved["farmer_id"] = str(request.farmer_id) if request.farmer_id else None
    if assistant_message is not None:
        saved["assistant_message"] = assistant_message
        saved["context_used"] = context_used
        saved["scenario_chat_history"] = scenario_history
    store.save_session(revised["session_id"], saved)
    if assistant_message is not None:
        base["scenario_chat_history"] = scenario_history
        store.save_session(request.base_session_id, base)
    if scenario_project is not None and request.farmer_id is not None:
        scenario_ids = [
            str(item)
            for item in scenario_project.get("scenario_session_ids") or []
            if item
        ]
        scenario_project.update(
            {
                "scenario_session_ids": [
                    revised["session_id"],
                    *[
                        item
                        for item in scenario_ids
                        if item != revised["session_id"]
                    ],
                ][:20],
                "last_scenario_session_id": revised["session_id"],
                "last_activity_at": datetime.now(UTC).isoformat(),
                **(
                    {"scenario_chat_history": scenario_history}
                    if assistant_message is not None
                    else {}
                ),
            }
        )
        store.save_farm_project(str(request.farmer_id), scenario_project)
        profile = _farmer_memory_v3(scenario_profile)
        store.save_farmer_profile(
            str(request.farmer_id),
            _put_project_in_memory(profile, scenario_project),
        )
        revised["farmer_project"] = scenario_project
    return revised


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
