"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from opentelemetry import trace

from idp.api.routes import audit, auth, batches, document_types, documents, review, type_suggestions, users, validation, validation_rules
from idp.config import get_settings
from idp.observability.otel import setup_tracing
from idp.storage.object_store import S3ObjectStore


def create_app() -> FastAPI:
    settings = get_settings()
    setup_tracing(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        S3ObjectStore(settings).ensure_bucket()
        yield
        # BatchSpanProcessor buffers spans and exports on a timer — without
        # this, spans from requests near process shutdown can be silently
        # dropped instead of reaching the exporter.
        trace.get_tracer_provider().shutdown()  # type: ignore[union-attr]

    app = FastAPI(title="Veritium", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(auth.router)
    app.include_router(batches.router)
    app.include_router(documents.router)
    app.include_router(document_types.router)
    app.include_router(review.router)
    app.include_router(type_suggestions.router)
    app.include_router(audit.router)
    app.include_router(users.router)
    app.include_router(validation.router)
    app.include_router(validation_rules.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
