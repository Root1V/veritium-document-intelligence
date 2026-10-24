"""The search's two models, straight to prometheus through axonium
(ADR-0009): embeddings for meaning, a reranker to order the candidates.
Both are optional to search: a model that is not granted, not configured or
not answering returns None, and search goes on by words and spelling."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from axonium import AsyncAxonium
from axonium.config import Timeouts

from idp.config import Settings
from idp.persistence.models import EMBEDDING_DIMENSIONS

log = logging.getLogger(__name__)
BATCH = 32
# Qwen3-Embedding is trained with an instruction on the query side only; documents go as they are.
QUERY_INSTRUCTION = "Instruct: Dado un término de búsqueda, encuentra los fragmentos de documentos bancarios que lo contienen o tratan de él\nQuery: "


class SearchModels:
    def __init__(self, settings: Settings) -> None:
        self.embedding_model = settings.search_embedding_model
        self.rerank_model = settings.search_rerank_model
        self._client: AsyncAxonium | None = None
        if (self.embedding_model or self.rerank_model) and settings.axonium_client_id and settings.axonium_client_secret is not None:
            timeout = settings.llm_request_timeout_seconds
            self._client = AsyncAxonium(
                client_id=settings.axonium_client_id,
                client_secret=settings.axonium_client_secret.get_secret_value(),
                timeouts=Timeouts(read=timeout, write=timeout),
            )
            if settings.environment == "prod":
                from idp.llm.port import on_premises

                on_premises(settings, self._client.config.gateway_base_url)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """One vector per text, or None when there is no embedding model to ask."""
        if self._client is None or not self.embedding_model or not texts:
            return None
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), BATCH):
                response = await self._client.embeddings.create(model=self.embedding_model, input=texts[start : start + BATCH])
                vectors += [item.embedding for item in sorted(response.data, key=lambda d: d.index or 0)]
        except Exception as exc:
            log.warning("búsqueda: sin embeddings de %s (%s); se busca por palabras", self.embedding_model, type(exc).__name__)
            return None
        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIMENSIONS for v in vectors):
            log.warning("búsqueda: %s no devolvió %d vectores de %d dimensiones", self.embedding_model, len(texts), EMBEDDING_DIMENSIONS)
            return None
        return vectors

    async def embed_query(self, query: str) -> list[float] | None:
        vectors = await self.embed([QUERY_INSTRUCTION + query])
        return vectors[0] if vectors else None

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """A relevance score per document, in the order given, or None without a reranker."""
        if self._client is None or not self.rerank_model or not documents:
            return None
        try:
            response = await self._client.rerank.create(model=self.rerank_model, query=query, documents=documents)
        except Exception as exc:
            log.warning("búsqueda: sin reordenar con %s (%s)", self.rerank_model, type(exc).__name__)
            return None
        scores = [0.0] * len(documents)
        for result in response.results:
            if result.index is not None and 0 <= result.index < len(documents):
                scores[result.index] = result.relevance_score or 0.0
        return scores


_current: SearchModels | None = None


@asynccontextmanager
async def search_models_lifespan(settings: Settings, *, models: SearchModels | None = None) -> AsyncGenerator[SearchModels]:
    """Open in the API's lifespan and at the worker's start; ``models`` replaces them in tests."""
    global _current
    _current = models or SearchModels(settings)
    try:
        yield _current
    finally:
        await _current.aclose()
        _current = None


def search_models(settings: Settings) -> SearchModels:
    """The open models, or ones without a client (search by words only) where none were opened."""
    return _current if _current is not None else _Disabled(settings)


class _Disabled(SearchModels):
    def __init__(self, settings: Settings) -> None:  # noqa: ARG002 — same signature, no client
        self.embedding_model = self.rerank_model = None
        self._client = None
