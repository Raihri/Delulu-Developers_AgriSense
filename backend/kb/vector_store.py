from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from db import get_database_client


TOKEN_RE = re.compile(r"[\w\u0980-\u09ff]+", flags=re.UNICODE)
EMBEDDING_DIMENSIONS = 192


def hashed_embedding(
    text: str, dimensions: int = EMBEDDING_DIMENSIONS
) -> list[float]:
    """Create the deterministic placeholder vector used by the current demo.

    pgvector stores and searches this vector, but the API explicitly does not
    claim that it is a production semantic embedding model.
    """

    vector = [0.0] * dimensions
    tokens = TOKEN_RE.findall(text.casefold())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any]


class SupabaseVectorStore:
    """pgvector-backed retrieval through the `match_rag_chunks` Supabase RPC."""

    def __init__(self, client: Any | None = None):
        self.client = client or get_database_client()

    def upsert_many(self, chunks: Iterable[dict[str, Any]]) -> int:
        rows: list[dict[str, Any]] = []
        for chunk in chunks:
            metadata = {key: value for key, value in chunk.items() if key != "text"}
            rows.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "content": chunk["text"],
                    "crop": chunk.get("crop"),
                    "topic": chunk.get("topic"),
                    "source_id": chunk["source_id"],
                    "source_locator": chunk["source_locator"],
                    "metadata": metadata,
                    "embedding": hashed_embedding(chunk["text"]),
                }
            )
        if rows:
            (
                self.client.table("rag_chunk")
                .upsert(rows, on_conflict="chunk_id")
                .execute()
            )
        return len(rows)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        crop: str | None = None,
        topic: str | None = None,
    ) -> list[SearchResult]:
        response = self.client.rpc(
            "match_rag_chunks",
            {
                "query_embedding": hashed_embedding(query),
                "match_count": max(1, min(limit, 20)),
                "filter_crop": crop,
                "filter_topic": topic,
            },
        ).execute()
        results: list[SearchResult] = []
        for row in response.data or []:
            metadata = row.get("metadata") or {}
            results.append(
                SearchResult(
                    chunk_id=row["chunk_id"],
                    text=row["content"],
                    score=float(row["similarity"]),
                    metadata=metadata,
                )
            )
        return results
