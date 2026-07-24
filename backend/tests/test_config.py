from __future__ import annotations

import pytest

from config import (
    GeminiConfigurationError,
    GeminiSettings,
    SupabaseConfigurationError,
    SupabasePostgresSettings,
    SupabaseSettings,
)


def test_gemini_requires_backend_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GeminiConfigurationError, match="GEMINI_API_KEY"):
        GeminiSettings.from_environment()


def test_gemini_key_is_hidden_from_repr(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    settings = GeminiSettings.from_environment()
    assert settings.model == "gemini-test"
    assert "secret-gemini-test-key" not in repr(settings)


def test_supabase_requires_backend_credentials(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(SupabaseConfigurationError, match="Missing backend"):
        SupabaseSettings.from_environment()


def test_supabase_rejects_example_placeholders(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://YOUR_PROJECT_REF.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_REPLACE_ME")
    with pytest.raises(SupabaseConfigurationError, match="placeholder"):
        SupabaseSettings.from_environment()


def test_direct_supabase_postgres_url_is_backend_only(monkeypatch) -> None:
    secret = "test-password-that-must-not-appear"
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        f"postgresql://postgres:{secret}@db.example.supabase.co:5432/postgres",
    )
    settings = SupabasePostgresSettings.from_environment()
    assert settings.connection_url.startswith("postgresql://")
    assert secret not in repr(settings)


def test_direct_supabase_postgres_rejects_placeholder(monkeypatch) -> None:
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres:REPLACE_ME@db.YOUR_PROJECT_REF.supabase.co/postgres",
    )
    with pytest.raises(SupabaseConfigurationError, match="placeholder"):
        SupabasePostgresSettings.from_environment()


def test_direct_url_can_use_non_secret_pooler_host_override(monkeypatch) -> None:
    secret = "encoded%2Fpassword"
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres:"
        f"{secret}@db.abcdefghijklmnopqrst.supabase.co:5432/postgres",
    )
    monkeypatch.setenv(
        "SUPABASE_DB_POOLER_HOST",
        "aws-1-ap-northeast-2.pooler.supabase.com",
    )

    settings = SupabasePostgresSettings.from_environment()

    assert "postgres.abcdefghijklmnopqrst" in settings.connection_url
    assert "aws-1-ap-northeast-2.pooler.supabase.com:5432" in settings.connection_url
    assert "db.abcdefghijklmnopqrst.supabase.co" not in settings.connection_url
    assert "encoded%2Fpassword" in settings.connection_url
