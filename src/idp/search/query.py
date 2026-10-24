"""Finding documents (VRT-59). Four ways in, each a ranked list of pieces:
words (Spanish full text, accents ignored), spelling (trigrams, for a name
or a number the OCR read with an error), meaning (the query's embedding
against the pieces') and the file name. The lists are fused by reciprocal
rank, the best are reordered by the reranker, and each document takes its
best piece — which says where it matched, never what it says: the content
is personal data and the list shows none.

A piece reached only by meaning is always someone's nearest neighbour, so
it counts only if the reranker finds it relevant, or, without a reranker,
if it is about as near as the nearest. A bare number skips meaning."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.persistence.models import Case, Document, ProcessProfile, ProcessProfileVersion, SearchChunk
from idp.search.chunks import WINDOW_CHARS
from idp.search.models import SearchModels

# Words and spelling are cheap (indexed) and a common name matches many
# pieces: they bring every match. Meaning always brings its nearest.
LEXICAL_CANDIDATES = 1000
CANDIDATES = 60
RERANKED = 20  # ~4k tokens a search, from the budget Veritium's extraction shares
# Of pg_trgm's word similarity: an 8-digit number with one digit misread scores 0.58 (its default is 0.6).
MIN_SPELLING = 0.5
RRF_K = 60
MAX_RESULTS = 200
# Only-by-meaning: the reranker's relevance (a probability), or, without one,
# cosine similarity near the query's best — this model's similarities bunch
# together (0.45-0.70 for right and wrong alike), so a fixed cut does not
# separate them, but the best and its close followers usually are right.
MIN_RELEVANCE = 0.3
# The floor, measured on this corpus: gibberish reaches 0.49, the weakest real
# description 0.51 — a thin margin; the reranker should replace it once it
# is fast and right in Spanish.
MEANING_BAND = 0.05
MIN_SIMILARITY = 0.50


@dataclass(frozen=True)
class Filters:
    status: str | None = None
    document_type: str | None = None
    needs_review: bool | None = None
    profile: str | None = None  # the process, by its key


@dataclass(frozen=True)
class Hit:
    document_id: uuid.UUID
    kind: str  # valores | texto | archivo
    page: int | None  # 0-indexed, for a text window


def filtered(stmt: Select[Any], filters: Filters) -> Select[Any]:
    """``stmt`` must already select from Document."""
    if filters.status is not None:
        stmt = stmt.where(Document.status == filters.status)
    if filters.document_type is not None:
        stmt = stmt.where(Document.document_type == filters.document_type)
    if filters.needs_review is not None:
        stmt = stmt.where(Document.needs_review == filters.needs_review)
    if filters.profile is not None:
        process = (
            select(Case.id)
            .join(ProcessProfileVersion, ProcessProfileVersion.id == Case.profile_version_id)
            .join(ProcessProfile, ProcessProfile.id == ProcessProfileVersion.profile_id)
            .where(ProcessProfile.key == filters.profile)
        )
        stmt = stmt.where(Document.case_id.in_(process))
    return stmt


def _pieces(*columns: Any) -> Select[Any]:
    return select(SearchChunk.id, SearchChunk.document_id, SearchChunk.kind, SearchChunk.page, SearchChunk.content, *columns).join(
        Document, Document.id == SearchChunk.document_id
    )


async def search(session: AsyncSession, models: SearchModels, q: str, filters: Filters = Filters()) -> list[Hit]:
    """The matching documents, best first (at most ``MAX_RESULTS``)."""
    q = q.strip()
    if not q:
        return []
    rows: dict[uuid.UUID, Any] = {}
    fused: dict[uuid.UUID, float] = {}
    lexical: set[uuid.UUID] = set()
    similarity: dict[uuid.UUID, float] = {}

    def take(ranked: list[Any], *, by_meaning: bool = False) -> None:
        for rank, row in enumerate(ranked):
            rows[row.id] = row
            fused[row.id] = fused.get(row.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            if by_meaning:
                similarity[row.id] = 1.0 - row.distance
            else:
                lexical.add(row.id)

    tsquery = func.websearch_to_tsquery(literal_column("'es_sin_tildes'::regconfig"), q)
    words = _pieces().where(SearchChunk.tsv.op("@@")(tsquery)).order_by(func.ts_rank_cd(SearchChunk.tsv, tsquery).desc()).limit(LEXICAL_CANDIDATES)
    take(list((await session.execute(filtered(words, filters))).all()))

    await session.execute(select(func.set_config("pg_trgm.word_similarity_threshold", str(MIN_SPELLING), True)))  # this transaction only
    spelling = _pieces().where(SearchChunk.content.op("%>")(q)).order_by(func.word_similarity(q, SearchChunk.content).desc()).limit(LEXICAL_CANDIDATES)
    take(list((await session.execute(filtered(spelling, filters))).all()))

    # A bare number or code means nothing to an embedding: its nearest pieces would be noise.
    if re.search(r"[^\W\d_]", q) and (vector := await models.embed_query(q)) is not None:
        distance = SearchChunk.embedding.cosine_distance(vector)
        meaning = _pieces(distance.label("distance")).where(SearchChunk.embedding_model == models.embedding_model).order_by(distance).limit(CANDIDATES)
        take(list((await session.execute(filtered(meaning, filters))).all()), by_meaning=True)

    named = filtered(select(Document.id).where(Document.original_filename.ilike(f"%{q}%")), filters).limit(LEXICAL_CANDIDATES)
    by_name = list((await session.scalars(named)).all())

    best = sorted(fused, key=fused.__getitem__, reverse=True)
    relevance = await models.rerank(q, [rows[i].content[:WINDOW_CHARS] for i in best[:RERANKED]])
    if relevance is not None:
        scored = dict(zip(best[:RERANKED], relevance, strict=True))
        keep = [i for i in best[:RERANKED] if i in lexical or scored[i] >= MIN_RELEVANCE]
        order = sorted(keep, key=scored.__getitem__, reverse=True) + [i for i in best[RERANKED:] if i in lexical]
    else:
        floor = max(MIN_SIMILARITY, max(similarity.values(), default=1.0) - MEANING_BAND)
        order = [i for i in best if i in lexical or similarity.get(i, 0.0) >= floor]

    hits: dict[uuid.UUID, Hit] = {}
    for chunk_id in order:
        row = rows[chunk_id]
        hits.setdefault(row.document_id, Hit(row.document_id, row.kind, row.page))
    for document_id in by_name:
        hits.setdefault(document_id, Hit(document_id, "archivo", None))
    return list(hits.values())[:MAX_RESULTS]
