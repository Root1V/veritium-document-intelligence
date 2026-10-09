"""FastAPI app factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from opentelemetry import trace

from idp.api.routes import api_clients, audit, auth, batches, bulk_jobs, events, calibration, cases, document_types, documents, evaluation, lenses, profiles, prompts, simulations, upload_sessions, review, semantic_catalog, type_suggestions, users, validation, validation_rules, webhooks
from idp.config import get_settings
from idp.llm.port import inference_lifespan
from idp.llm.prompts import current as current_prompts
from idp.llm.prompts import set_published
from idp.observability.otel import setup_tracing
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import DocumentTypeRepository, LensRepository, ProcessProfileRepository, PromptEditRepository, PromptRepository, SemanticCatalogRepository
from idp.storage.object_store import S3ObjectStore
from idp.events import bus
from idp.pipeline import bulk
from idp.webhooks import dispatcher


def create_app() -> FastAPI:
    settings = get_settings()
    setup_tracing(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        S3ObjectStore(settings).ensure_bucket()
        async with get_session_factory(settings)() as session:
            await SemanticCatalogRepository(session).ensure_seed()
            await ProcessProfileRepository(session).ensure_seed()
            await DocumentTypeRepository(session).ensure_seed()
            await LensRepository(session).ensure_seed()
            # Keep the text of the prompts this code runs with (VRT-46), and
            # put in effect the ones AI specialists published (VRT-63).
            await PromptRepository(session).record([(p.name, p.code_version, p.text) for p in current_prompts()])
            set_published(await PromptEditRepository(session).published_texts())
        stop = asyncio.Event()
        task = asyncio.create_task(dispatcher.run(settings, stop)) if settings.webhook_dispatcher_enabled else None
        feeder = asyncio.create_task(bulk.run(settings, stop))  # releases bulk jobs' cases a few at a time (VRT-48)
        # The event bus, when configured: outbox out, commands in (VRT-49).
        events = asyncio.create_task(bus.run(settings, stop)) if settings.event_bus_brokers else None
        async with inference_lifespan(settings):  # the in-process executor and rule drafting call models
            yield
        stop.set()
        await feeder
        if events is not None:
            await events
        if task is not None:
            await task
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
    app.include_router(cases.router)
    app.include_router(documents.router)
    app.include_router(document_types.router)
    app.include_router(document_types.admin_router)
    app.include_router(review.router)
    app.include_router(type_suggestions.router)
    app.include_router(audit.router)
    app.include_router(users.router)
    app.include_router(validation.router)
    app.include_router(validation_rules.router)
    app.include_router(semantic_catalog.router)
    app.include_router(profiles.router)
    app.include_router(webhooks.router)
    app.include_router(evaluation.router)
    app.include_router(calibration.router)
    app.include_router(simulations.router)
    app.include_router(lenses.router)
    app.include_router(prompts.router)
    app.include_router(upload_sessions.router)
    app.include_router(bulk_jobs.router)
    app.include_router(api_clients.router)
    app.include_router(events.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
