from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parent
# `PROJECT_ROOT` remains the backend root for runtime-owned files. Downloaded
# source assets intentionally remain one level above it in `dataset/`.
PROJECT_ROOT = BACKEND_ROOT
REPOSITORY_ROOT = BACKEND_ROOT.parent
DATASET_ROOT = REPOSITORY_ROOT / "dataset"
KB_ROOT = BACKEND_ROOT / "kb"
CURATED_ROOT = KB_ROOT / "curated"
SOURCE_REGISTRY = KB_ROOT / "sources.yaml"
load_dotenv(BACKEND_ROOT / ".env")
load_dotenv(REPOSITORY_ROOT / ".env", override=False)


class SupabaseConfigurationError(RuntimeError):
    """Raised when the backend has no safe Supabase server configuration."""


class GeminiConfigurationError(RuntimeError):
    """Raised when server-side Gemini features are not configured."""


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = field(repr=False)
    model: str

    @classmethod
    def from_environment(cls) -> "GeminiSettings":
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
        if not api_key:
            raise GeminiConfigurationError(
                "Missing backend Gemini configuration: GEMINI_API_KEY"
            )
        if not model:
            raise GeminiConfigurationError(
                "Missing backend Gemini configuration: GEMINI_MODEL"
            )
        return cls(api_key=api_key, model=model)


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    secret_key: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "SupabaseSettings":
        url = os.environ.get("SUPABASE_URL", "").strip()
        # New sb_secret_ keys are preferred; the legacy service_role variable is
        # supported during migration. Neither value may be sent to a browser.
        secret_key = (
            os.environ.get("SUPABASE_SECRET_KEY", "").strip()
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", url),
                ("SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY)", secret_key),
            )
            if not value
        ]
        if missing:
            raise SupabaseConfigurationError(
                "Missing backend Supabase configuration: " + ", ".join(missing)
            )
        if "YOUR_PROJECT" in url or "REPLACE_ME" in secret_key:
            raise SupabaseConfigurationError(
                "Replace the placeholder Supabase URL and secret key in .env"
            )
        if not url.startswith("https://"):
            raise SupabaseConfigurationError("SUPABASE_URL must start with https://")
        return cls(url=url.rstrip("/"), secret_key=secret_key)


@dataclass(frozen=True)
class SupabasePostgresSettings:
    """Backend-only direct connection used for migrations and API queries."""

    connection_url: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "SupabasePostgresSettings":
        connection_url = os.environ.get("SUPABASE_DB_URL", "").strip()
        if not connection_url:
            raise SupabaseConfigurationError(
                "Missing backend Supabase configuration: SUPABASE_DB_URL"
            )
        if "YOUR_PROJECT" in connection_url or "REPLACE_ME" in connection_url:
            raise SupabaseConfigurationError(
                "Replace the placeholder SUPABASE_DB_URL in .env"
            )

        parsed = urlsplit(connection_url)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise SupabaseConfigurationError(
                "SUPABASE_DB_URL must start with postgresql:// or postgres://"
            )
        if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
            raise SupabaseConfigurationError(
                "SUPABASE_DB_URL must include a host, user and database name"
            )
        pooler_host = os.environ.get("SUPABASE_DB_POOLER_HOST", "").strip()
        if pooler_host:
            connection_url = _use_session_pooler(connection_url, pooler_host)
        return cls(connection_url=connection_url)


def _use_session_pooler(connection_url: str, pooler_host: str) -> str:
    """Rewrite a direct Supabase URL to an explicit, non-secret pooler host."""

    if (
        "/" in pooler_host
        or ":" in pooler_host
        or not pooler_host.endswith(".pooler.supabase.com")
    ):
        raise SupabaseConfigurationError(
            "SUPABASE_DB_POOLER_HOST must be a Supabase pooler hostname without a port"
        )
    parsed = urlsplit(connection_url)
    direct_host = parsed.hostname or ""
    prefix = "db."
    suffix = ".supabase.co"
    if not (direct_host.startswith(prefix) and direct_host.endswith(suffix)):
        raise SupabaseConfigurationError(
            "SUPABASE_DB_POOLER_HOST override requires a direct db.<project>.supabase.co URL"
        )
    project_ref = direct_host[len(prefix) : -len(suffix)]
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    pooler_username = (
        username if username.endswith(f".{project_ref}") else f"{username}.{project_ref}"
    )
    netloc = (
        f"{quote(pooler_username, safe='')}:{quote(password, safe='')}"
        f"@{pooler_host}:5432"
    )
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def supabase_api_configured() -> bool:
    try:
        SupabaseSettings.from_environment()
    except SupabaseConfigurationError:
        return False
    return True


def supabase_postgres_configured() -> bool:
    try:
        SupabasePostgresSettings.from_environment()
    except SupabaseConfigurationError:
        return False
    return True


def supabase_configured() -> bool:
    """Return whether either supported server-side Supabase path is configured."""

    return supabase_api_configured() or supabase_postgres_configured()
