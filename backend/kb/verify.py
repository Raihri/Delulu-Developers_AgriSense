from __future__ import annotations

import json
from typing import Any

from config import CURATED_ROOT, SupabaseConfigurationError
from db import get_database_client
from kb.build import CSV_TABLES, _read_curated_csv, _source_rows
from kb.vector_store import SupabaseVectorStore


def verify_seed(client: Any | None = None) -> dict[str, object]:
    """Verify exact seed counts, build status and one cited pgvector result."""

    database = client or get_database_client()
    session = getattr(database, "session", None)
    if callable(session):
        with session():
            return _verify_seed(database)
    return _verify_seed(database)


def _verify_seed(database: Any) -> dict[str, object]:
    expected_counts = {
        "agri_source": len(_source_rows()),
        **{
            table: len(_read_curated_csv(CURATED_ROOT / filename, table))
            for filename, table in CSV_TABLES.items()
        },
    }
    rag_rows = (
        database.table("rag_chunk").select("chunk_id").execute().data or []
    )
    expected_counts["rag_chunk"] = sum(
        1
        for line in (CURATED_ROOT / "rag_chunks.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
    actual_counts = {
        table: len(database.table(table).select("*").execute().data or [])
        for table in expected_counts
        if table != "rag_chunk"
    }
    actual_counts["rag_chunk"] = len(rag_rows)

    mismatches = {
        table: {"expected": expected, "actual": actual_counts.get(table)}
        for table, expected in expected_counts.items()
        if actual_counts.get(table) != expected
    }
    metadata_rows = (
        database.table("build_metadata")
        .select("key,value")
        .in_("key", ["quality_status", "storage_backend"])
        .execute()
        .data
        or []
    )
    metadata = {row["key"]: row["value"] for row in metadata_rows}
    search_results = SupabaseVectorStore(database).search(
        "maize fertilizer nitrogen timing", crop="maize", limit=1
    )
    citation_ok = bool(
        search_results
        and search_results[0].metadata.get("source_id")
        and search_results[0].metadata.get("source_locator")
    )
    passed = (
        not mismatches
        and metadata.get("quality_status") == "passed"
        and metadata.get("storage_backend") == "supabase_postgres_pgvector"
        and citation_ok
    )
    return {
        "status": "passed" if passed else "failed",
        "counts": actual_counts,
        "count_mismatches": mismatches,
        "quality_status": metadata.get("quality_status"),
        "storage_backend": metadata.get("storage_backend"),
        "cited_vector_search": citation_ok,
    }


def main() -> None:
    try:
        result = verify_seed()
    except (SupabaseConfigurationError, ImportError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
