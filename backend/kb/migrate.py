from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from config import (
    PROJECT_ROOT,
    SupabaseConfigurationError,
    SupabasePostgresSettings,
)


MIGRATION_ROOT = PROJECT_ROOT / "supabase" / "migrations"
MIGRATION_PATH = MIGRATION_ROOT / "202607240001_agrisense.sql"


class MigrationError(RuntimeError):
    """Raised when a Supabase migration cannot be safely completed."""


def _redact(message: str, connection_url: str) -> str:
    redacted = message.replace(connection_url, "[redacted]")
    password = urlsplit(connection_url).password
    if password:
        redacted = redacted.replace(password, "[redacted]")
        redacted = redacted.replace(unquote(password), "[redacted]")
    return redacted


def apply_migration(
    connection_url: str | None = None,
    migration_path: Path = MIGRATION_PATH,
) -> dict[str, object]:
    """Apply the checked-in migration once through a direct Postgres connection."""

    if connection_url is None:
        connection_url = SupabasePostgresSettings.from_environment().connection_url
    migration_sql = migration_path.read_text(encoding="utf-8")
    migration_id = migration_path.stem
    migration_sha256 = hashlib.sha256(migration_sql.encode("utf-8")).hexdigest()

    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(
            connection_url,
            connect_timeout=10,
            sslmode="require",
            row_factory=dict_row,
        ) as connection:
            connection.execute(
                """
                create table if not exists public.agrisense_schema_migration (
                  migration_id text primary key,
                  sha256 text not null,
                  applied_at timestamptz not null default timezone('utc', now())
                )
                """
            )
            existing = connection.execute(
                """
                select migration_id, sha256, applied_at
                from public.agrisense_schema_migration
                where migration_id = %s
                """,
                (migration_id,),
            ).fetchone()
            if existing:
                if existing["sha256"] != migration_sha256:
                    raise MigrationError(
                        "The applied migration has the same ID but a different hash"
                    )
                return {
                    "status": "already_applied",
                    "migration_id": migration_id,
                    "sha256": migration_sha256,
                }

            connection.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                ("agrisense_schema_migration",),
            )
            connection.execute(migration_sql)
            connection.execute(
                """
                insert into public.agrisense_schema_migration (migration_id, sha256)
                values (%s, %s)
                """,
                (migration_id, migration_sha256),
            )
        return {
            "status": "applied",
            "migration_id": migration_id,
            "sha256": migration_sha256,
        }
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(
            "Supabase migration failed: " + _redact(str(exc), connection_url)
        ) from exc


def apply_all_migrations(
    connection_url: str | None = None,
) -> dict[str, object]:
    """Apply every checked-in SQL migration in filename order."""
    paths = sorted(MIGRATION_ROOT.glob("*.sql"))
    if not paths:
        raise MigrationError("No Supabase migrations were found")
    results = [
        apply_migration(connection_url=connection_url, migration_path=path)
        for path in paths
    ]
    return {
        "status": "applied_all",
        "migrations": results,
    }


def main() -> None:
    try:
        result = apply_all_migrations()
    except (SupabaseConfigurationError, MigrationError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
