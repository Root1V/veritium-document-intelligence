"""Keeping a case's documents searchable (VRT-59). Each run, after its
verdict, re-indexes the whole case: its documents' extracted values (as
corrected) and the text read from them. A piece whose content did not
change keeps its embedding, so a re-run only asks the model for what is new.
Never fails a run: whoever calls it logs and goes on."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from idp.config import Settings
from idp.parsing.normalize import ParsedDocument
from idp.parsing.store import load_parsed
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, Document, SearchChunk
from idp.search.chunks import Chunk, document_chunks
from idp.search.models import SearchModels, search_models
from idp.storage.object_store import ObjectStore, S3ObjectStore

log = logging.getLogger(__name__)


async def index_case(session: AsyncSession, store: ObjectStore, models: SearchModels, case_id: uuid.UUID) -> int:
    """Replace the case's pieces, in the active unit; returns how many. Commits."""
    case = await session.get(Case, case_id)
    if case is None or case.anonymized_at is not None:
        return 0
    documents = (await session.scalars(select(Document).where(Document.case_id == case_id).options(selectinload(Document.extraction)))).all()
    parsed_by_key: dict[str, ParsedDocument | None] = {}
    pieces: list[tuple[uuid.UUID, Chunk]] = []
    for document in documents:
        if document.status == "segmented" or not document.storage_key:  # its segments are indexed instead; a removed file has nothing
            continue
        if document.storage_key not in parsed_by_key:
            parsed_by_key[document.storage_key] = await asyncio.to_thread(load_parsed, store, document.storage_key)
        pages = (document.page_start, document.page_end) if document.page_start is not None and document.page_end is not None else None
        payload = document.extraction.payload if document.extraction is not None else None
        pieces += [(document.id, chunk) for chunk in document_chunks(payload, parsed_by_key[document.storage_key], pages)]

    kept = {
        (row.document_id, row.content_hash): row.embedding
        for row in (await session.execute(
            select(SearchChunk.document_id, SearchChunk.content_hash, SearchChunk.embedding)
            .where(SearchChunk.case_id == case_id, SearchChunk.embedding_model == models.embedding_model, SearchChunk.embedding.is_not(None))
        )).all()
    }
    missing = [chunk.content for document_id, chunk in pieces if (document_id, chunk.content_hash) not in kept]
    fresh = dict(zip(missing, await models.embed(missing) or [], strict=False))

    await session.execute(delete(SearchChunk).where(SearchChunk.case_id == case_id))
    for document_id, chunk in pieces:
        embedding = kept.get((document_id, chunk.content_hash))
        embedding = embedding if embedding is not None else fresh.get(chunk.content)
        session.add(SearchChunk(
            case_id=case_id, document_id=document_id, kind=chunk.kind, page=chunk.page, content=chunk.content, content_hash=chunk.content_hash,
            embedding=embedding, embedding_model=models.embedding_model if embedding is not None else None,
        ))
    await session.commit()
    return len(pieces)


async def index_case_after_run(settings: Settings, case_id: uuid.UUID) -> None:
    """The run's last step, in the case's unit: a failure here leaves the case searchable as it was."""
    try:
        async with get_session_factory(settings)() as session:
            await index_case(session, S3ObjectStore(settings), search_models(settings), case_id)
    except Exception:
        log.exception("búsqueda: no se pudo indexar el expediente %s", case_id)


async def reindex_all(settings: Settings) -> int:
    """Index every case of every unit (scripts/reindex_search.py): the cases processed before VRT-59. Returns how many pieces."""
    with tenancy.system():  # a maintenance job over every business unit; each case is then indexed in its own
        async with get_session_factory(settings)() as session:
            cases = (await session.execute(select(Case.id, Case.tenant).where(Case.anonymized_at.is_(None)))).all()
    store, models, total = S3ObjectStore(settings), search_models(settings), 0
    for case_id, tenant in cases:
        with tenancy.acting_for(tenant):
            async with get_session_factory(settings)() as session:
                total += await index_case(session, store, models, case_id)
    return total
