from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import db_dependency

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response, db: Session = Depends(db_dependency)) -> dict:
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if all_ok else 503
    return {"status": "ok" if all_ok else "degraded", "checks": checks}


@router.get("/metrics")
def metrics() -> Response:
    """Phase 19: Prometheus text exposition format. Unauthenticated like /health and
    /ready (app/main.py) — a Prometheus scraper typically hits this without an API
    key, the same operational-infra reasoning as the other two."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
