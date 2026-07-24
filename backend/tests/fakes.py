from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kb.vector_store import cosine


@dataclass
class FakeResponse:
    data: list[dict[str, Any]]


class FakeQuery:
    def __init__(
        self,
        client: "FakeSupabaseClient",
        table: str,
        action: str = "select",
        payload: Any = None,
        conflict_key: str | None = None,
    ):
        self.client = client
        self.table_name = table
        self.action = action
        self.payload = payload
        self.conflict_key = conflict_key
        self.filters: list[tuple[str, str, Any]] = []
        self.row_limit: int | None = None

    def select(self, *_: Any, **__: Any) -> "FakeQuery":
        self.action = "select"
        return self

    def eq(self, column: str, value: Any) -> "FakeQuery":
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "FakeQuery":
        self.filters.append(("in", column, values))
        return self

    def limit(self, value: int) -> "FakeQuery":
        self.row_limit = value
        return self

    def upsert(
        self, payload: Any, *, on_conflict: str, **__: Any
    ) -> "FakeQuery":
        self.action = "upsert"
        self.payload = payload
        self.conflict_key = on_conflict
        return self

    def insert(self, payload: Any, **__: Any) -> "FakeQuery":
        self.action = "insert"
        self.payload = payload
        return self

    def execute(self) -> FakeResponse:
        rows = self.client.tables.setdefault(self.table_name, [])
        if self.action == "upsert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            keys = (self.conflict_key or "").split(",")
            result: list[dict[str, Any]] = []
            for payload in payloads:
                item = dict(payload)
                existing = next(
                    (
                        row
                        for row in rows
                        if keys and all(row.get(key) == item.get(key) for key in keys)
                    ),
                    None,
                )
                if existing is None:
                    rows.append(item)
                    result.append(item)
                else:
                    existing.update(item)
                    result.append(existing)
            return FakeResponse(result)
        if self.action == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            result = []
            for payload in payloads:
                item = dict(payload)
                item.setdefault("id", f"fake-{self.table_name}-{len(rows) + 1}")
                rows.append(item)
                result.append(item)
            return FakeResponse(result)

        selected = [dict(row) for row in rows]
        for operator, column, expected in self.filters:
            if operator == "eq":
                selected = [row for row in selected if row.get(column) == expected]
            else:
                selected = [row for row in selected if row.get(column) in expected]
        if self.row_limit is not None:
            selected = selected[: self.row_limit]
        return FakeResponse(selected)


class FakeRpcQuery:
    def __init__(
        self, client: "FakeSupabaseClient", name: str, parameters: dict[str, Any]
    ):
        self.client = client
        self.name = name
        self.parameters = parameters

    def execute(self) -> FakeResponse:
        if self.name != "match_rag_chunks":
            raise KeyError(self.name)
        query = self.parameters["query_embedding"]
        crop = self.parameters.get("filter_crop")
        topic = self.parameters.get("filter_topic")
        results = []
        for row in self.client.tables.get("rag_chunk", []):
            if crop and row.get("crop") != crop:
                continue
            if topic and row.get("topic") != topic:
                continue
            results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "content": row["content"],
                    "metadata": row["metadata"],
                    "similarity": cosine(query, row["embedding"]),
                }
            )
        results.sort(key=lambda row: row["similarity"], reverse=True)
        return FakeResponse(results[: self.parameters["match_count"]])


class FakeSupabaseClient:
    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def rpc(self, name: str, parameters: dict[str, Any]) -> FakeRpcQuery:
        return FakeRpcQuery(self, name, parameters)
