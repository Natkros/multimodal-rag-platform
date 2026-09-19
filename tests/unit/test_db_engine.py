from __future__ import annotations

from unittest.mock import patch

from app.core.config import get_settings


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


def test_sqlite_engine_gets_no_pool_kwargs():
    import app.models.db as db_module

    settings = _settings(database_url="sqlite:///:memory:")
    with patch.object(db_module, "get_settings", return_value=settings), patch(
        "app.models.db.create_engine"
    ) as mock_create:
        db_module._engine = None
        db_module.get_engine()

    mock_create.assert_called_once_with("sqlite:///:memory:", connect_args={"check_same_thread": False})
    db_module._engine = None


def test_postgres_engine_gets_pool_kwargs():
    import app.models.db as db_module

    settings = _settings(
        database_url="postgresql://user:pass@localhost/db",
        db_pool_size=7,
        db_max_overflow=3,
        db_pool_pre_ping=True,
    )
    with patch.object(db_module, "get_settings", return_value=settings), patch(
        "app.models.db.create_engine"
    ) as mock_create:
        db_module._engine = None
        db_module.get_engine()

    mock_create.assert_called_once_with(
        "postgresql://user:pass@localhost/db", pool_size=7, max_overflow=3, pool_pre_ping=True
    )
    db_module._engine = None
