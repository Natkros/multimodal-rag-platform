from __future__ import annotations

from collections.abc import Generator

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.db import get_db


def settings_dependency() -> Settings:
    return get_settings()


def db_dependency() -> Generator[Session, None, None]:
    yield from get_db()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Phase 18: no-op when API_KEY isn't set (this project's default — local dev
    has no auth, per README's Security section) — auth activates the moment an
    operator sets one, without a separate feature flag to also remember to flip.
    Applied per-router in app/main.py, not globally, so /health and /ready stay
    reachable without a key (standard for k8s liveness/readiness probes hitting the
    API before any key is provisioned to them). See
    docs/decisions/0018-phase18-security-hardening.md."""
    settings = get_settings()
    if not settings.api_key:
        # Falsy, not just `is None`: the real .env ships `API_KEY=` (present but
        # empty) so a fresh clone has an explicit, discoverable line to fill in —
        # an empty string must mean "not configured" the same way unset does,
        # or every local dev/test run would be locked out by default.
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")
