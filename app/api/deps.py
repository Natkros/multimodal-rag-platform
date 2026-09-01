from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.db import get_db


def settings_dependency() -> Settings:
    return get_settings()


def db_dependency() -> Generator[Session, None, None]:
    yield from get_db()
