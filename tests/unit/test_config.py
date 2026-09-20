from __future__ import annotations

from app.core.config import Settings, get_settings


def test_env_example_produces_a_bootable_config(monkeypatch):
    """Phase 30: literally following the README's Quickstart (`cp .env.example
    .env`) crashed the app on startup - `.env.example` ships
    CONTEXT_MAX_CHUNKS_PER_DOCUMENT= (present, empty, meant as "unset" for this
    `int | None` field), and pydantic-settings tried to parse "" as an int rather
    than treating an empty value as unset. This test reproduces the exact env var
    combination from .env.example rather than only testing the isolated field, so
    a similar bug in a different field would also be caught here."""
    monkeypatch.setenv("CONTEXT_MAX_CHUNKS_PER_DOCUMENT", "")
    settings = Settings(_env_file=None)
    assert settings.context_max_chunks_per_document is None


def test_context_max_chunks_per_document_accepts_a_real_integer(monkeypatch):
    monkeypatch.setenv("CONTEXT_MAX_CHUNKS_PER_DOCUMENT", "3")
    settings = Settings(_env_file=None)
    assert settings.context_max_chunks_per_document == 3


def test_context_max_chunks_per_document_defaults_to_none_when_unset(monkeypatch):
    monkeypatch.delenv("CONTEXT_MAX_CHUNKS_PER_DOCUMENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.context_max_chunks_per_document is None


def test_get_settings_is_cached(test_settings):
    assert get_settings() is get_settings()
