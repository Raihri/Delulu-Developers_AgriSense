from __future__ import annotations

from functools import lru_cache
from typing import Any

from config import (
    SupabaseConfigurationError,
    SupabasePostgresSettings,
    SupabaseSettings,
    supabase_api_configured,
    supabase_postgres_configured,
)


@lru_cache(maxsize=1)
def get_database_client() -> Any:
    """Create a backend-only client for either supported Supabase path.

    The HTTP API/secret-key path is preferred when both are set. A direct
    Postgres URL is accepted for migrations, seeding and server-side API use.
    Neither credential may reach browser code.
    """

    if supabase_api_configured():
        from supabase import create_client

        settings = SupabaseSettings.from_environment()
        return create_client(settings.url, settings.secret_key)
    if supabase_postgres_configured():
        from postgres import PostgresClient

        return PostgresClient(SupabasePostgresSettings.from_environment())
    raise SupabaseConfigurationError(
        "Missing backend Supabase configuration. Set either SUPABASE_DB_URL, "
        "or SUPABASE_URL plus SUPABASE_SECRET_KEY."
    )


def get_supabase_client() -> Any:
    """Backward-compatible name for the shared Supabase database client."""

    return get_database_client()
