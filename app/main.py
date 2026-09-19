from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.deps import require_api_key
from app.api.routes import documents, health, query
from app.core.config import get_settings
from app.middleware.observability import ObservabilityMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.models.db import init_db
from app.services.observability.logging_config import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    # Read fresh on every call, not once at import time — app.main is imported once
    # per test process, but tests/conftest.py's test_settings fixture changes env
    # vars and clears get_settings' cache per test; a module-level `settings`
    # snapshot from first import would silently keep using stale config (CORS
    # origins, and now Phase 18's api_key/rate_limit settings) for every later test.
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Multimodal RAG Platform",
        description="Production-grade multimodal Retrieval-Augmented Generation API.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Starlette's add_middleware() builds the stack in reverse call order: the
    # FIRST middleware added ends up INNERMOST (closest to the router), and the
    # LAST one added ends up OUTERMOST (closest to the client) — see
    # Starlette.build_middleware_stack(). GZip is added first specifically so it
    # sits innermost, directly wrapping the route handlers, and sees a real
    # Content-Length before any of the BaseHTTPMiddleware-based middlewares below
    # convert the response into a streaming shell with no known length (which, in
    # an earlier ordering, defeated `minimum_size` entirely and compressed every
    # response regardless of size — caught by this phase's own gzip test, not by
    # inspection). See docs/decisions/0020-phase20-performance.md.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # /health and /ready stay key-free (k8s liveness/readiness probes hit these
    # before any key is provisioned to them); every other route requires
    # X-API-Key when API_KEY is set (see app/api/deps.py::require_api_key — a
    # no-op when it isn't, which is this project's default).
    app.include_router(health.router)
    app.include_router(documents.router, dependencies=[Depends(require_api_key)])
    app.include_router(query.router, dependencies=[Depends(require_api_key)])

    return app


app = create_app()
