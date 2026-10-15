"""Seeing a case's personal data (VRT-58): masked by default for everyone.
Whoever works the case — operador, admin, a connected system — can ask to
see it, and each time is recorded (``data_access_log``, and a log line
without the data):

- from the screen, ``POST /v1/cases/{id}/reveal`` opens a window of
  ``WINDOW`` on that case for that person: one click, one record, however
  often the page refreshes;
- a system adds ``?reveal=true`` to the call: one call, one record.

Visor and especialista IA always see it masked."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_principal
from idp.auth.authenticate import Principal
from idp.domain.pii import Masker
from idp.domain.semantic import SemanticCatalog
from idp.persistence.models import Case, DataAccess, Document, Extraction, ProcessProfileVersion
from idp.pipeline.orchestrator import load_semantic_catalog

log = logging.getLogger(__name__)
REVEALERS = ("operador", "admin", "integracion")
WINDOW = timedelta(minutes=15)


def can_reveal(role: str) -> bool:
    return role in REVEALERS


@dataclass
class CaseData:
    """What a case's masker is built from: the catalog that classifies its
    fields, its documents' data and its process data."""

    catalog: SemanticCatalog | None
    documents: list[tuple[str | None, dict | None]]
    process_data: list[Any]

    def masker(self, *more: tuple[str | None, dict | None]) -> Masker:
        """``more``: other values of the case's fields, e.g. one a correction replaced."""
        return Masker.for_documents(self.catalog, [*self.documents, *more], extra=self.process_data)


async def case_data(session: AsyncSession, case: Case) -> CaseData:
    loaded = await load_semantic_catalog(session, case.profile_version.semantic_catalog_version if case.profile_version else None)
    return CaseData(
        catalog=loaded[0] if loaded else None,
        documents=[(d.document_type, d.extraction.payload if d.extraction else None) for d in case.documents],
        process_data=list((case.request_input_payload or {}).values()),
    )


async def _case_data_by_id(session: AsyncSession, case_id: Any) -> CaseData | None:
    """Column reads only: loading the case's objects again would refresh the
    ones a listing already holds and drop their loaded relationships."""
    head = (await session.execute(
        select(Case.request_input_payload, ProcessProfileVersion.semantic_catalog_version)
        .outerjoin(ProcessProfileVersion, ProcessProfileVersion.id == Case.profile_version_id)
        .where(Case.id == case_id)
    )).first()
    if head is None:
        return None
    rows = (await session.execute(
        select(Document.document_type, Extraction.payload).outerjoin(Extraction, Extraction.document_id == Document.id).where(Document.case_id == case_id)
    )).all()
    loaded = await load_semantic_catalog(session, head.semantic_catalog_version)
    return CaseData(catalog=loaded[0] if loaded else None, documents=[(r.document_type, r.payload) for r in rows],
                    process_data=list((head.request_input_payload or {}).values()))


async def case_masker(session: AsyncSession, case: Case) -> Masker:
    """The masker for one case: its documents' data, classified by the catalog it resolves against."""
    return (await case_data(session, case)).masker()


def actor_of(principal: Principal) -> str:
    return f"sistema · {principal.client.client_id}" if principal.client else principal.user.email


async def record(
    session: AsyncSession, principal: Principal, *, action: str, what: str, case_id: Any = None, document_id: Any = None,
    reason: str | None = None, until: datetime | None = None,
) -> DataAccess:
    """One access to personal data, in the unit's log (committed now: it must stay even if the response fails)."""
    entry = DataAccess(action=action, what=what, case_id=case_id, document_id=document_id, actor=actor_of(principal), role=principal.role,
                       channel="api" if principal.client else "web", reason=reason, until=until)
    session.add(entry)
    await session.commit()
    log.info("datos personales: %s %s (%s) por %s [%s]", action, what, case_id or document_id, entry.actor, principal.role)
    return entry


async def open_window(session: AsyncSession, principal: Principal, case: Case, reason: str | None) -> DataAccess:
    return await record(session, principal, action="ver_datos", what="expediente (pantalla)", case_id=case.id, reason=reason,
                        until=datetime.now(UTC) + WINDOW)


async def window_open(session: AsyncSession, principal: Principal, case_id: Any) -> bool:
    stmt = select(DataAccess.id).where(
        DataAccess.case_id == case_id, DataAccess.actor == actor_of(principal), DataAccess.action == "ver_datos", DataAccess.until > datetime.now(UTC)
    )
    return can_reveal(principal.role) and await session.scalar(stmt.limit(1)) is not None


@dataclass
class Disclosure:
    """Whether this request shows the data in clear — and, if so, it is recorded when used."""

    principal: Principal
    reveal: bool

    async def masker(self, session: AsyncSession, case: Case, *, what: str, document_id: Any = None) -> Masker:
        if await window_open(session, self.principal, case.id):
            return Masker.clear()
        if not self.reveal:
            return await case_masker(session, case)
        await record(session, self.principal, action="ver_datos", what=what, case_id=case.id, document_id=document_id)
        return Masker.clear()


async def get_disclosure(
    principal: Annotated[Principal, Depends(get_principal)],
    reveal: Annotated[bool, Query(description="Muestra los datos personales sin enmascarar; queda registrado (VRT-58).")] = False,
) -> Disclosure:
    if reveal and not can_reveal(principal.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tu rol no permite ver los datos personales sin enmascarar")
    return Disclosure(principal=principal, reveal=reveal)


class CaseMaskers:
    """For a response that spans several cases (a list, the review queue):
    each item masked with its own case's masker, built once per case."""

    def __init__(self, session: AsyncSession, principal: Principal | None) -> None:
        """``principal`` None: always masked (agents over MCP, A2A)."""
        self._session, self._principal = session, principal
        self._data: dict[Any, CaseData | None] = {}
        self._visible: dict[Any, bool] = {}
        self._cache: dict[Any, Masker] = {}

    async def visible(self, case_id: Any) -> bool:
        if case_id not in self._visible:
            self._visible[case_id] = self._principal is not None and case_id is not None and await window_open(self._session, self._principal, case_id)
        return self._visible[case_id]

    async def data(self, case_id: Any) -> CaseData | None:
        if case_id not in self._data:
            self._data[case_id] = await _case_data_by_id(self._session, case_id) if case_id is not None else None
        return self._data[case_id]

    async def __call__(self, case_id: Any, *more: tuple[str | None, dict | None]) -> Masker:
        if await self.visible(case_id):
            return Masker.clear()
        if more:
            data = await self.data(case_id)
            return data.masker(*more) if data else Masker.for_documents(None, list(more))
        if case_id not in self._cache:
            data = await self.data(case_id)
            self._cache[case_id] = data.masker() if data else Masker()
        return self._cache[case_id]
