from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from config import CURATED_ROOT, KB_ROOT, SupabaseConfigurationError
from db import get_database_client
from kb.registry import load_registry
from kb.validate import sha256_file, validate_repository
from kb.vector_store import SupabaseVectorStore


CSV_TABLES = {
    "admin_aliases.csv": "admin_alias",
    "admin_aez_crosswalk.csv": "admin_aez_crosswalk",
    "crop_variety.csv": "crop_variety",
    "crop_soil_suitability.csv": "crop_soil_suitability",
    "crop_water_stage.csv": "crop_water_stage",
    "soil_water_profile.csv": "soil_water_profile",
    "crop_calendar.csv": "crop_calendar",
    "fertilizer_recommendation.csv": "fertilizer_recommendation",
    "yield_baseline.csv": "yield_baseline",
    "cost_baseline.csv": "cost_baseline",
}

INTEGER_COLUMNS = {
    "aez_id",
    "duration_min_days",
    "duration_base_days",
    "duration_max_days",
    "stage_order",
    "duration_days",
    "sow_start_month",
    "sow_end_month",
    "harvest_start_month",
    "harvest_end_month",
}
NUMERIC_COLUMNS = {
    "yield_min_t_ha",
    "yield_base_t_ha",
    "yield_max_t_ha",
    "kc_start",
    "kc_end",
    "root_depth_start_m",
    "root_depth_end_m",
    "total_available_moisture_mm_per_m",
    "max_rain_infiltration_mm_per_day",
    "yield_target_t_ha",
    "rate_min",
    "rate_max",
    "area_acres",
    "production_mt",
    "canonical_yield_t_ha",
    "quantity_per_acre",
    "unit_price_bdt",
    "cost_per_acre_bdt",
}
BOOLEAN_COLUMNS = {"local_observation", "editable"}


def _coerce_value(column: str, value: str) -> Any:
    if value == "":
        return None
    if column in INTEGER_COLUMNS:
        return int(value)
    if column in NUMERIC_COLUMNS:
        return float(value)
    if column in BOOLEAN_COLUMNS:
        normalized = value.casefold()
        if normalized not in {"true", "false"}:
            raise ValueError(f"Invalid boolean for {column}: {value!r}")
        return normalized == "true"
    return value


def _record_id(table: str, row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{table}:{payload}".encode("utf-8")).hexdigest()


def _read_curated_csv(path: Path, table: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = []
        for raw in csv.DictReader(handle):
            row = {column: _coerce_value(column, value) for column, value in raw.items()}
            row["record_id"] = _record_id(table, row)
            rows.append(row)
        return rows


def _batches(rows: list[dict[str, Any]], size: int = 200) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _upsert_rows(
    client: Any, table: str, rows: list[dict[str, Any]], conflict_key: str
) -> int:
    for batch in _batches(rows):
        client.table(table).upsert(batch, on_conflict=conflict_key).execute()
    return len(rows)


def _source_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    explicit = {
        "id",
        "publisher",
        "title",
        "url",
        "asset_type",
        "version",
        "accessed_at",
        "language",
        "geography",
        "topics",
        "download_status",
        "curation_status",
        "safety_status",
        "licence",
        "redistribution_allowed",
        "machine_readable",
        "sha256",
    }
    for source in load_registry()["sources"]:
        rows.append(
            {
                "id": source["id"],
                "publisher": source["publisher"],
                "title": source["title"],
                "url": source.get("url"),
                "asset_type": source["asset_type"],
                "version": str(source["version"]),
                "accessed_at": source["accessed_at"],
                "language": source["language"],
                "geography": source["geography"],
                "topics": source["topics"],
                "download_status": source["download_status"],
                "curation_status": source["curation_status"],
                "safety_status": source["safety_status"],
                "licence": source["licence"],
                "redistribution_allowed": source["redistribution_allowed"],
                "machine_readable": str(source["machine_readable"]).lower(),
                "sha256": source.get("sha256"),
                "metadata": {
                    key: value for key, value in source.items() if key not in explicit
                },
            }
        )
    return rows


def seed_supabase(
    client: Any | None = None, *, validate: bool = True
) -> dict[str, object]:
    """Upsert the reviewed source/curated slice into an already-migrated project."""

    if validate:
        report = validate_repository()
        if report["errors"]:
            raise RuntimeError("KB validation failed: " + "; ".join(report["errors"]))

    database = client or get_database_client()
    session = getattr(database, "session", None)
    if callable(session):
        with session():
            return _seed_into(database)
    return _seed_into(database)


def _seed_into(supabase: Any) -> dict[str, object]:
    """Write the reviewed slice using an optional caller-managed DB session."""

    counts: dict[str, int] = {}
    source_rows = _source_rows()
    counts["agri_source"] = _upsert_rows(supabase, "agri_source", source_rows, "id")

    for filename, table in CSV_TABLES.items():
        rows = _read_curated_csv(CURATED_ROOT / filename, table)
        counts[table] = _upsert_rows(supabase, table, rows, "record_id")

    chunks: list[dict[str, Any]] = []
    with (CURATED_ROOT / "rag_chunks.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunks.append(json.loads(line))
    counts["rag_chunk"] = SupabaseVectorStore(supabase).upsert_many(chunks)

    manifest_path = KB_ROOT / "curation_manifest.yaml"
    metadata = [
        {"key": "schema_version", "value": "1.0.0"},
        {"key": "built_at", "value": datetime.now(UTC).isoformat()},
        {"key": "source_registry_version", "value": load_registry()["schema_version"]},
        {"key": "curation_manifest_sha256", "value": sha256_file(manifest_path)},
        {"key": "quality_status", "value": "passed"},
        {"key": "storage_backend", "value": "supabase_postgres_pgvector"},
    ]
    counts["build_metadata"] = _upsert_rows(
        supabase, "build_metadata", metadata, "key"
    )
    return {
        "backend": "supabase_postgres_pgvector",
        "counts": counts,
        "quality_status": "passed",
    }


def main() -> None:
    try:
        result = seed_supabase()
    except SupabaseConfigurationError as exc:
        raise SystemExit(
            f"{exc}\nApply the Supabase migration and configure one backend-only "
            "connection method from .env.example."
        ) from exc
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
