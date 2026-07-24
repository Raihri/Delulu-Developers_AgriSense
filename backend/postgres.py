from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import unquote, urlsplit

from config import SupabasePostgresSettings


IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
ALLOWED_TABLES = {
    "agri_source",
    "admin_alias",
    "admin_aez_crosswalk",
    "crop_variety",
    "crop_soil_suitability",
    "crop_water_stage",
    "soil_water_profile",
    "crop_calendar",
    "fertilizer_recommendation",
    "yield_baseline",
    "cost_baseline",
    "rag_chunk",
    "build_metadata",
    "farmer_profile",
    "farmer_session",
    "trace_record",
}
JSONB_COLUMNS = {
    "agri_source": {"metadata"},
    "rag_chunk": {"metadata"},
    "build_metadata": {"value"},
    "farmer_profile": {"profile_json"},
    "farmer_session": {"state_json"},
    "trace_record": {"params_json", "display_output_json"},
}
VECTOR_COLUMNS = {"rag_chunk": {"embedding"}}


class SupabasePostgresError(RuntimeError):
    """A direct-database failure with credentials removed from its message."""


@dataclass(frozen=True)
class PostgresResponse:
    data: list[dict[str, Any]]


def _identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe database identifier: {value!r}")
    return value


def _projection(value: str) -> list[str] | None:
    if value.strip() == "*":
        return None
    columns = [_identifier(part.strip()) for part in value.split(",") if part.strip()]
    if not columns:
        raise ValueError("A select projection cannot be empty")
    return columns


class PostgresQuery:
    """Small query builder matching the subset of supabase-py used by AgriSense."""

    def __init__(self, client: "PostgresClient", table: str):
        self.client = client
        self.table_name = table
        self.action = "select"
        self.columns: list[str] | None = None
        self.payload: Any = None
        self.conflict_columns: list[str] = []
        self.filters: list[tuple[str, str, Any]] = []
        self.row_limit: int | None = None

    def select(self, columns: str = "*", **_: Any) -> "PostgresQuery":
        self.action = "select"
        self.columns = _projection(columns)
        return self

    def eq(self, column: str, value: Any) -> "PostgresQuery":
        self.filters.append(("eq", _identifier(column), value))
        return self

    def in_(self, column: str, values: Sequence[Any]) -> "PostgresQuery":
        self.filters.append(("in", _identifier(column), list(values)))
        return self

    def limit(self, value: int) -> "PostgresQuery":
        if value < 0:
            raise ValueError("Query limit cannot be negative")
        self.row_limit = value
        return self

    def upsert(
        self,
        payload: Any,
        *,
        on_conflict: str,
        **_: Any,
    ) -> "PostgresQuery":
        self.action = "upsert"
        self.payload = payload
        self.conflict_columns = [
            _identifier(part.strip())
            for part in on_conflict.split(",")
            if part.strip()
        ]
        if not self.conflict_columns:
            raise ValueError("Upsert requires at least one conflict column")
        return self

    def insert(self, payload: Any, **_: Any) -> "PostgresQuery":
        self.action = "insert"
        self.payload = payload
        return self

    def execute(self) -> PostgresResponse:
        if self.action == "select":
            return self.client._select(
                self.table_name,
                columns=self.columns,
                filters=self.filters,
                limit=self.row_limit,
            )
        return self.client._write(
            self.table_name,
            action=self.action,
            payload=self.payload,
            conflict_columns=self.conflict_columns,
        )


class PostgresRpcQuery:
    def __init__(
        self,
        client: "PostgresClient",
        function_name: str,
        parameters: dict[str, Any],
    ):
        self.client = client
        self.function_name = function_name
        self.parameters = parameters

    def execute(self) -> PostgresResponse:
        if self.function_name != "match_rag_chunks":
            raise ValueError(f"Unsupported database function: {self.function_name}")
        return self.client._match_rag_chunks(self.parameters)


class PostgresClient:
    """Server-only Supabase Postgres adapter.

    This is intentionally narrow: it exposes only the table and RPC operations
    used by this backend. Browser clients must use Supabase Auth/RLS instead.
    """

    def __init__(self, settings: SupabasePostgresSettings):
        self.settings = settings
        self._session_connection: Any | None = None

    def table(self, name: str) -> PostgresQuery:
        if name not in ALLOWED_TABLES:
            raise ValueError(f"Unsupported database table: {name}")
        return PostgresQuery(self, name)

    def rpc(self, name: str, parameters: dict[str, Any]) -> PostgresRpcQuery:
        return PostgresRpcQuery(self, name, parameters)

    @contextmanager
    def session(self) -> Iterator["PostgresClient"]:
        """Reuse one connection for a bounded seed or verification operation."""

        if self._session_connection is not None:
            yield self
            return
        connection = self._connect()
        self._session_connection = connection
        try:
            yield self
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._session_connection = None
            connection.close()

    @contextmanager
    def _connection_scope(self) -> Iterator[Any]:
        if self._session_connection is not None:
            yield self._session_connection
            return
        with self._connect() as connection:
            yield connection

    def _connect(self) -> Any:
        try:
            import psycopg
            from pgvector.psycopg import register_vector
            from psycopg.rows import dict_row

            connection = psycopg.connect(
                self.settings.connection_url,
                connect_timeout=10,
                sslmode="require",
                row_factory=dict_row,
                # Supabase Session Pooler can hand a transaction to a backend that
                # still has psycopg's generated prepared-statement name. Disable
                # client-side prepared statements rather than risking collisions.
                prepare_threshold=None,
            )
            register_vector(connection)
            return connection
        except Exception as exc:
            raise self._safe_error("connect to", exc) from exc

    def _safe_error(self, action: str, exc: Exception) -> SupabasePostgresError:
        message = str(exc).replace(self.settings.connection_url, "[redacted]")
        password = urlsplit(self.settings.connection_url).password
        if password:
            message = message.replace(password, "[redacted]")
            message = message.replace(unquote(password), "[redacted]")
        return SupabasePostgresError(
            f"Could not {action} Supabase Postgres: {message}"
        )

    def _select(
        self,
        table: str,
        *,
        columns: list[str] | None,
        filters: list[tuple[str, str, Any]],
        limit: int | None,
    ) -> PostgresResponse:
        from psycopg import sql

        selected = (
            sql.SQL("*")
            if columns is None
            else sql.SQL(", ").join(sql.Identifier(column) for column in columns)
        )
        statement = sql.SQL("select {} from public.{}").format(
            selected, sql.Identifier(table)
        )
        parameters: list[Any] = []
        predicates: list[Any] = []
        for operator, column, expected in filters:
            if operator == "eq":
                predicates.append(
                    sql.SQL("{} = %s").format(sql.Identifier(column))
                )
                parameters.append(expected)
            elif expected:
                predicates.append(
                    sql.SQL("{} = any(%s)").format(sql.Identifier(column))
                )
                parameters.append(expected)
            else:
                predicates.append(sql.SQL("false"))
        if predicates:
            statement += sql.SQL(" where ") + sql.SQL(" and ").join(predicates)
        if limit is not None:
            statement += sql.SQL(" limit %s")
            parameters.append(limit)

        try:
            with self._connection_scope() as connection:
                rows = connection.execute(statement, parameters).fetchall()
            return PostgresResponse([dict(row) for row in rows])
        except SupabasePostgresError:
            raise
        except Exception as exc:
            raise self._safe_error(f"query {table} in", exc) from exc

    def _write(
        self,
        table: str,
        *,
        action: str,
        payload: Any,
        conflict_columns: list[str],
    ) -> PostgresResponse:
        from psycopg import sql

        raw_rows = payload if isinstance(payload, list) else [payload]
        rows = [dict(row) for row in raw_rows]
        if not rows:
            return PostgresResponse([])
        columns = list(rows[0])
        if not columns or any(list(row) != columns for row in rows):
            raise ValueError("All inserted rows must have the same ordered columns")
        for column in columns:
            _identifier(column)

        value_groups: list[Any] = []
        parameters: list[Any] = []
        for row in rows:
            value_groups.append(
                sql.SQL("({})").format(
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns)
                )
            )
            parameters.extend(
                self._adapt_value(table, column, row[column]) for column in columns
            )

        statement = sql.SQL("insert into public.{} ({}) values {}").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.SQL(", ").join(value_groups),
        )
        if action == "upsert":
            update_columns = [
                column for column in columns if column not in conflict_columns
            ]
            statement += sql.SQL(" on conflict ({}) ").format(
                sql.SQL(", ").join(
                    sql.Identifier(column) for column in conflict_columns
                )
            )
            if update_columns:
                statement += sql.SQL("do update set ") + sql.SQL(", ").join(
                    sql.SQL("{} = excluded.{}").format(
                        sql.Identifier(column), sql.Identifier(column)
                    )
                    for column in update_columns
                )
            else:
                statement += sql.SQL("do nothing")
        statement += sql.SQL(" returning *")

        try:
            with self._connection_scope() as connection:
                result = connection.execute(statement, parameters).fetchall()
            return PostgresResponse([dict(row) for row in result])
        except SupabasePostgresError:
            raise
        except Exception as exc:
            raise self._safe_error(f"{action} {table} in", exc) from exc

    def _adapt_value(self, table: str, column: str, value: Any) -> Any:
        if column in JSONB_COLUMNS.get(table, set()):
            from psycopg.types.json import Jsonb

            return Jsonb(value)
        if column in VECTOR_COLUMNS.get(table, set()):
            from pgvector import Vector

            return Vector(value)
        return value

    def _match_rag_chunks(self, parameters: dict[str, Any]) -> PostgresResponse:
        from pgvector import Vector

        query_embedding = parameters.get("query_embedding")
        if not isinstance(query_embedding, Iterable):
            raise ValueError("match_rag_chunks requires query_embedding")
        values = (
            Vector(query_embedding),
            int(parameters.get("match_count", 5)),
            parameters.get("filter_crop"),
            parameters.get("filter_topic"),
        )
        statement = """
            select chunk_id, content, metadata, similarity
            from public.match_rag_chunks(%s, %s, %s, %s)
        """
        try:
            with self._connection_scope() as connection:
                rows = connection.execute(statement, values).fetchall()
            return PostgresResponse([dict(row) for row in rows])
        except SupabasePostgresError:
            raise
        except Exception as exc:
            raise self._safe_error("run match_rag_chunks in", exc) from exc
