from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from config import (
    CURATED_ROOT,
    DATASET_ROOT,
    KB_ROOT,
    PROJECT_ROOT,
    REPOSITORY_ROOT,
    SOURCE_REGISTRY,
)
from kb.registry import load_registry


REGISTRY_REQUIRED = {
    "id",
    "publisher",
    "title",
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
    "update_check",
}


def _source_path(relative: str) -> Path:
    """Resolve repo-root downloaded assets and backend-owned artifacts."""
    root = REPOSITORY_ROOT if relative.startswith("dataset/") else PROJECT_ROOT
    return root / relative


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_entries(source: dict[str, Any]) -> list[tuple[str, str]]:
    assets: list[tuple[str, str]] = []
    if source.get("local_path") and source.get("sha256"):
        assets.append((source["local_path"], source["sha256"]))
    for selected in source.get("selected_files", []):
        if selected.get("path") and selected.get("sha256"):
            assets.append((selected["path"], selected["sha256"]))
    return assets


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _validate_manifest(
    errors: list[str], warnings: list[str], registered_ids: set[str]
) -> None:
    manifest_path = KB_ROOT / "curation_manifest.yaml"
    if not manifest_path.exists():
        errors.append("Missing kb/curation_manifest.yaml")
        return
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0.0":
        errors.append("Curation manifest schema_version must be 1.0.0")
    seen_paths: set[str] = set()
    for item in manifest.get("files", []):
        relative = item.get("path", "")
        if relative in seen_paths:
            errors.append(f"Duplicate manifest path: {relative}")
            continue
        seen_paths.add(relative)
        path = _source_path(relative)
        if not path.exists():
            errors.append(f"Missing curated manifest file: {relative}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != item.get("sha256"):
            errors.append(f"Curated hash mismatch: {relative}")
        if path.suffix == ".csv":
            columns, rows = _csv_rows(path)
            missing = set(item.get("required_columns", [])) - set(columns)
            if missing:
                errors.append(f"{relative} missing columns: {sorted(missing)}")
            if len(rows) != item.get("row_count"):
                errors.append(
                    f"{relative} row count {len(rows)} != manifest {item.get('row_count')}"
                )
            for index, row in enumerate(rows, start=2):
                source_id = row.get("source_id")
                if source_id and source_id not in registered_ids:
                    errors.append(f"{relative}:{index} unknown source_id {source_id}")
                if "source_id" in columns and not source_id:
                    errors.append(f"{relative}:{index} has no source_id")
                if "source_locator" in columns and not row.get("source_locator"):
                    errors.append(f"{relative}:{index} has no source_locator")
                if "curation_status" in columns and row.get("curation_status") != "human_reviewed":
                    errors.append(f"{relative}:{index} is not human_reviewed")
                secondary = row.get("precision_source_id")
                if secondary and secondary not in registered_ids:
                    errors.append(f"{relative}:{index} unknown precision_source_id {secondary}")
        elif path.suffix == ".jsonl":
            rows = []
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{relative}:{index} invalid JSON: {exc}")
                    continue
                rows.append(row)
                if row.get("source_id") not in registered_ids:
                    errors.append(f"{relative}:{index} has unknown source_id")
                if not row.get("source_locator"):
                    errors.append(f"{relative}:{index} has no source_locator")
                if row.get("curation_status") != "human_reviewed":
                    errors.append(f"{relative}:{index} is not human_reviewed")
            if len(rows) != item.get("row_count"):
                errors.append(
                    f"{relative} row count {len(rows)} != manifest {item.get('row_count')}"
                )
        elif path.suffix in {".yaml", ".yml"}:
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                errors.append(f"{relative} invalid YAML: {exc}")
        else:
            warnings.append(f"No content-schema checks configured for {relative}")

    actual_curated = {
        str(path.relative_to(PROJECT_ROOT))
        for path in CURATED_ROOT.iterdir()
        if path.is_file() and path.name != "README.md"
    }
    missing_from_manifest = actual_curated - seen_paths
    if missing_from_manifest:
        errors.append(f"Curated files absent from manifest: {sorted(missing_from_manifest)}")


def _validate_hdx(errors: list[str]) -> None:
    path = DATASET_ROOT / "hdx/bgd_admin3.geojson"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    pcodes = [feature.get("properties", {}).get("adm3_pcode") for feature in features]
    if len(features) != 507:
        errors.append(f"HDX ADM3 feature count is {len(features)}, expected 507")
    if None in pcodes or len(set(pcodes)) != 507:
        errors.append("HDX ADM3 P-codes are missing or not uniquely 507")


def _validate_curated_policies(errors: list[str], registered_ids: set[str]) -> None:
    precedence = yaml.safe_load(
        (CURATED_ROOT / "source_precedence.yaml").read_text(encoding="utf-8")
    )
    rules = precedence.get("rules", [])
    ranks = [rule.get("rank") for rule in rules]
    source_ids = [rule.get("source_id") for rule in rules]
    if len(ranks) != len(set(ranks)) or sorted(ranks) != list(range(1, len(ranks) + 1)):
        errors.append("Source-precedence ranks must be unique and contiguous")
    if not set(source_ids) <= registered_ids:
        errors.append("Source precedence refers to an unregistered source")
    required_authorities = {
        "fao_56",
        "fao_cropwat",
        "barc_frg_2024",
        "brri_released_varieties",
        "bari_agro_tech_handbook",
        "ais_crop_calendar",
        "ais_crop_production",
        "srdi_soil_maps",
        "hdx_cod_bgd",
        "bbs_agri_yearbook",
        "project_demo_assumptions",
    }
    if set(source_ids) != required_authorities:
        errors.append("Source precedence does not contain the reviewed authority set")

    water = yaml.safe_load(
        (CURATED_ROOT / "water_assumptions.yaml").read_text(encoding="utf-8")
    )
    if water.get("method_authority", {}).get("source_id") != "fao_56":
        errors.append("FAO-56 Rev.1 must remain the water method authority")
    if water.get("effective_rainfall", {}).get("fixed_percentage_allowed") is not False:
        errors.append("Fixed-percentage effective rainfall must be disabled")
    if water.get("irrigation", {}).get("default_efficiency") is not None:
        errors.append("Irrigation efficiency must not have a silent default")
    if water.get("paddy_rice", {}).get("water_suitability_score_allowed") is not False:
        errors.append("Paddy water suitability must fail closed")

    _, costs = _csv_rows(CURATED_ROOT / "cost_baseline.csv")
    if any(
        row["source_id"] != "project_demo_assumptions"
        or row["editable"].casefold() != "true"
        or row["safety_status"] != "provisional"
        for row in costs
    ):
        errors.append("Every current cost row must remain an editable provisional assumption")


def _validate_supabase_contract(errors: list[str]) -> None:
    migration = (
        PROJECT_ROOT
        / "supabase"
        / "migrations"
        / "202607240001_agrisense.sql"
    )
    if not migration.exists():
        errors.append("Missing initial Supabase migration")
        return
    sql = migration.read_text(encoding="utf-8").casefold()
    required_fragments = {
        "pgvector extension": "create extension if not exists vector",
        "source table": "create table public.agri_source",
        "session table": "create table public.farmer_session",
        "trace table": "create table public.trace_record",
        "rag vector": "embedding extensions.vector(192)",
        "retrieval RPC": "function public.match_rag_chunks",
        "row-level security": "enable row level security",
        "service-only grants": "to service_role",
    }
    for label, fragment in required_fragments.items():
        if fragment not in sql:
            errors.append(f"Supabase migration missing {label}")

    env_example = PROJECT_ROOT / ".env.example"
    if not env_example.exists():
        errors.append("Missing .env.example for Supabase configuration")
    else:
        env_text = env_example.read_text(encoding="utf-8")
        required_variables = {
            "SUPABASE_DB_URL",
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY",
        }
        declared_variables = {
            line.split("=", 1)[0].strip()
            for line in env_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }
        if not required_variables.issubset(declared_variables):
            errors.append(".env.example is missing Supabase backend variables")


def _validate_pdf_pages(source: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    if not source.get("pages") or not source.get("local_path", "").lower().endswith(".pdf"):
        return
    path = _source_path(source["local_path"])
    if not path.exists():
        return
    try:
        from pypdf import PdfReader
    except ImportError:
        warnings.append(f"Skipped page-count check for {source['id']}: pypdf is not installed")
        return
    actual = len(PdfReader(str(path)).pages)
    if actual != source["pages"]:
        errors.append(f"{source['id']} has {actual} pages, registry says {source['pages']}")


def validate_repository() -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    schema_path = KB_ROOT / "source_registry.schema.json"
    if not schema_path.exists():
        errors.append("Missing kb/source_registry.schema.json")
    else:
        try:
            json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid registry JSON schema: {exc}")

    registry = load_registry(SOURCE_REGISTRY)
    if registry.get("schema_version") != "2.0.0":
        errors.append("Source registry schema_version must be 2.0.0")
    vocab = registry.get("status_vocabulary", {})
    sources = registry["sources"]
    ids = [source.get("id") for source in sources]
    if len(ids) != len(set(ids)):
        errors.append("Source IDs must be unique")

    seen_paths: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    for source in sources:
        missing = REGISTRY_REQUIRED - set(source)
        if missing:
            errors.append(f"{source.get('id', '<unknown>')} missing fields: {sorted(missing)}")
            continue
        for status_field in ("download_status", "curation_status", "safety_status"):
            if source[status_field] not in vocab.get(status_field, []):
                errors.append(
                    f"{source['id']} has invalid {status_field}: {source[status_field]}"
                )
        assets = _asset_entries(source)
        if source["download_status"] == "downloaded" and not assets:
            errors.append(f"{source['id']} is downloaded but has no hashed local asset")
        for relative, expected_hash in assets:
            path = _source_path(relative)
            if not path.exists():
                errors.append(f"{source['id']} missing asset: {relative}")
                continue
            actual_hash = sha256_file(path)
            if actual_hash != expected_hash:
                errors.append(f"{source['id']} hash mismatch: {relative}")
            if relative in seen_paths:
                errors.append(
                    f"Asset path overlap: {relative} in {source['id']} and {seen_paths[relative]}"
                )
            seen_paths[relative] = source["id"]
            if expected_hash in seen_hashes:
                errors.append(
                    f"Byte-identical asset overlap: {source['id']} and "
                    f"{seen_hashes[expected_hash]}"
                )
            seen_hashes[expected_hash] = source["id"]
        _validate_pdf_pages(source, errors, warnings)

    by_id = {source["id"]: source for source in sources}
    frg = by_id.get("barc_frg_2024", {})
    if (
        frg.get("local_path") != "dataset/FRG English 30.10.2024.pdf"
        or frg.get("pages") != 260
        or frg.get("sha256")
        != "fba07db1be079e3e4ab2110242edc640bbc97b83274725b3ff391d35dbcdb927"
    ):
        errors.append("FRG registration does not match the reviewed local asset")
    hdx = by_id.get("hdx_cod_bgd", {})
    if hdx.get("language") != "en":
        errors.append("HDX ADM3 language must be en; Bengali aliases are separate")
    bbs = by_id.get("bbs_agri_yearbook", {})
    if "bbs_2024_carrot_table_3_9_29" not in bbs.get("quarantine_ids", []):
        errors.append("BBS carrot Table 3.9.29 is not registered as quarantined")

    quarantine_path = CURATED_ROOT / "data_quality_quarantine.yaml"
    quarantine = yaml.safe_load(quarantine_path.read_text(encoding="utf-8"))
    quarantine_ids = {item["id"] for item in quarantine.get("items", [])}
    if "bbs_2024_carrot_table_3_9_29" not in quarantine_ids:
        errors.append("BBS carrot quarantine record is missing")

    _validate_hdx(errors)
    _validate_curated_policies(errors, set(ids))
    _validate_supabase_contract(errors)
    _validate_manifest(errors, warnings, set(ids))
    return {"errors": errors, "warnings": sorted(set(warnings))}


def main() -> None:
    report = validate_repository()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
