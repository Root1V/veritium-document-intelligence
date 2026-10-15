"""GET /v1/data-access — who saw or removed the unit's personal data (VRT-58):
each «Ver datos», each original downloaded, each search by a datum, each
suppression and expiry. Admins only; the log never holds the data itself."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.deps import get_db_session, require_role
from idp.persistence.models import Case, DataAccess

router = APIRouter(prefix="/v1/data-access", tags=["data-access"], dependencies=[Depends(require_role("admin"))])

ACTION_LABEL = {
    "ver_datos": "Vio los datos",
    "descargar_original": "Descargó el original",
    "buscar": "Buscó por un dato",
    "suprimir": "Suprimió los datos",
    "vencer": "Venció el plazo de conservación",
}


class DataAccessEntry(BaseModel):
    id: uuid.UUID
    at: datetime
    action: str
    action_label: str
    what: str
    actor: str
    role: str
    channel: str
    reason: str | None
    case_id: uuid.UUID | None
    case_ref: str | None
    document_id: uuid.UUID | None


@router.get("", response_model=list[DataAccessEntry])
async def list_data_access(case_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0, session: AsyncSession = Depends(get_db_session)) -> list[DataAccessEntry]:
    stmt = select(DataAccess, Case.external_ref).outerjoin(Case, Case.id == DataAccess.case_id).order_by(DataAccess.created_at.desc())
    if case_id is not None:
        stmt = stmt.where(DataAccess.case_id == case_id)
    rows = (await session.execute(stmt.limit(min(limit, 500)).offset(offset))).all()
    return [
        DataAccessEntry(
            id=e.id, at=e.created_at, action=e.action, action_label=ACTION_LABEL.get(e.action, e.action), what=e.what, actor=e.actor, role=e.role,
            channel=e.channel, reason=e.reason, case_id=e.case_id, case_ref=ref, document_id=e.document_id,
        )
        for e, ref in rows
    ]
