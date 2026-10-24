"""Hybrid document search (VRT-59) against real Postgres: a document is found
by a number as written or misread by one digit, by a name without accents or
capitals, by meaning when no word matches, and by its file name — only in
its business unit and, when asked, its process. Each hit says where it
matched and nothing of what it says. Re-indexing asks the model only for
what changed, and removing a case's personal data removes what was indexed."""

from __future__ import annotations

import hashlib
import math
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from idp.api.app import create_app
from idp.auth.security import hash_password
from idp.domain.process_profile_seed import convenios_definition
from idp.parsing.normalize import ParsedBlock, ParsedDocument
from idp.parsing.store import save_parsed
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import EMBEDDING_DIMENSIONS, Case, DataAccess, Document, Extraction, ProcessProfile, ProcessProfileVersion, SearchChunk, User
from idp.persistence.repositories import UserRepository
from idp.pipeline import retention
from idp.search.index import index_case
from idp.search.models import SearchModels
from idp.search.query import Filters, search

pytestmark = [pytest.mark.usefixtures("require_postgres")]
DNI = "42285866"
_PASSWORD = "test-password-busqueda"
# The fake embedding's "meanings": a text is near another when they share a topic.
_TOPICS = [r"ingreso|remuneraci|sueldo|salario", r"inmueble|hipoteca|vivienda"]


class FakeModels(SearchModels):
    def __init__(self) -> None:
        self.embedding_model, self.rerank_model, self._client = "fake-embedding", None, None
        self.embedded: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded += texts
        vectors = []
        for text in texts:
            v = [1.0 if re.search(t, text.lower()) else 0.0 for t in _TOPICS] + [0.0] * (EMBEDDING_DIMENSIONS - len(_TOPICS))
            v[len(_TOPICS) + int(hashlib.sha256(text.encode()).hexdigest(), 16) % (EMBEDDING_DIMENSIONS - len(_TOPICS))] = 0.3  # its own, unlike any other
            norm = math.sqrt(sum(x * x for x in v))
            vectors.append([x / norm for x in v])
        return vectors


class MemoryStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def put(self, key: str, data, content_type: str = "") -> None:  # noqa: ANN001
        self.files[key] = data if isinstance(data, bytes) else data.read()

    def get(self, key: str) -> bytes:
        return self.files[key]

    def delete(self, key: str) -> None:
        self.files.pop(key, None)


async def _profile(session, key: str) -> tuple[str, uuid.UUID]:
    definition = convenios_definition()
    profile = ProcessProfile(key=f"{key}-{uuid.uuid4().hex[:6]}", name=key)
    profile.versions.append(ProcessProfileVersion(version=1, status="published", definition=definition.model_dump(mode="json"),
                                                  content_hash=definition.content_hash(), semantic_catalog_version=1, created_by="test"))
    session.add(profile)
    await session.flush()
    return profile.key, profile.versions[0].id


async def _document(session, store: MemoryStore, unit: str, version_id: uuid.UUID | None, *, filename: str, values: dict, text: str) -> tuple[uuid.UUID, uuid.UUID]:
    case = Case(status="completed", profile_version_id=version_id)
    session.add(case)
    await session.flush()
    key = f"{unit}/{case.id}/{filename}"
    save_parsed(store, key, ParsedDocument(backend="t", page_count=2, blocks=[
        ParsedBlock(region_id=1, text="Página de portada", page=0, bbox=[0, 0, 1, 1], confidence=0.9),
        ParsedBlock(region_id=2, text=text, page=1, bbox=[0, 0, 1, 1], confidence=0.9),
    ]))
    doc = Document(case_id=case.id, status="completed", document_type="payslip", storage_key=key, original_filename=filename)
    session.add(doc)
    await session.flush()
    session.add(Extraction(document_id=doc.id, schema_version="1", parser_backend="rapidocr", extraction_method="agentic",
                           payload={k: {"value": v, "confidence": 0.9} for k, v in values.items()}))
    await session.commit()
    return case.id, doc.id


@pytest.mark.asyncio
async def test_a_document_is_found_by_number_misreading_name_meaning_and_file_in_its_unit_and_process(live_settings, scratch_unit, other_unit):
    factory, store, models = get_session_factory(live_settings), MemoryStore(), FakeModels()
    with tenancy.acting_for(other_unit):
        async with factory() as session:  # the same person in another unit: never seen from this one
            case, _ = await _document(session, store, other_unit, None, filename="boleta-otra.pdf", values={"employee_code": DNI}, text="Boleta")
            await index_case(session, store, models, case)
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            convenios, convenios_v = await _profile(session, "convenios")
            hipotecario, hipotecario_v = await _profile(session, "hipotecario")
            case_a, payslip = await _document(session, store, scratch_unit, convenios_v, filename="BX-7731-enero.pdf",
                                              values={"employee_name": "José Pérez Quispe", "employee_code": DNI, "net_pay": 2345.5},
                                              text="Boleta de pago. Remuneración neta del mes de enero, abonada en cuenta")
            case_b, appraisal = await _document(session, store, scratch_unit, hipotecario_v, filename="tasacion.pdf",
                                                values={"owner_name": "María Torres Vega", "owner_dni": "10293847"},
                                                text="Informe de tasación del inmueble para el crédito hipotecario")
            for case in (case_a, case_b):
                await index_case(session, store, models, case)

            async def found(q: str, filters: Filters = Filters()) -> list[tuple[uuid.UUID, str, int | None]]:
                return [(h.document_id, h.kind, h.page) for h in await search(session, models, q, filters)]

            assert await found(DNI) == [(payslip, "valores", None)], "as written; the other unit's is not here"
            assert (await found("42285966"))[0] == (payslip, "valores", None), "one digit misread by the OCR"
            assert (await found("jose perez"))[0][:2] == (payslip, "valores"), "no accents, no capitals"
            assert await found("ingresos del trabajador") == [(payslip, "texto", 1)], "by meaning only: no word in common, the appraisal is not near"
            assert await found("tasacion") == [(appraisal, "texto", 1)]
            assert await found("BX-7731") == [(payslip, "archivo", None)], "only its file name says it"
            assert await found(DNI, Filters(profile=hipotecario)) == [], "only that process's cases"
            assert await found(DNI, Filters(profile=convenios)) == [(payslip, "valores", None)]
            assert await found("zzqx wvbn") == []


@pytest.mark.asyncio
async def test_reindexing_asks_the_model_only_for_what_changed(live_settings, scratch_unit):
    factory, store, models = get_session_factory(live_settings), MemoryStore(), FakeModels()
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            case, doc = await _document(session, store, scratch_unit, None, filename="b.pdf", values={"net_pay": 100}, text="Remuneración neta")
            assert await index_case(session, store, models, case) == 3 and len(models.embedded) == 3  # values, and each page's text
            models.embedded.clear()
            await index_case(session, store, models, case)
            assert models.embedded == [], "nothing changed: the embeddings stay"
            extraction = await session.scalar(select(Extraction).where(Extraction.document_id == doc))
            extraction.payload = {"net_pay": {"value": 120, "confidence": 1.0}}  # a correction
            await session.commit()
            await index_case(session, store, models, case)
            assert models.embedded == ["net pay: 120"]
            assert await session.scalar(select(func.count()).select_from(SearchChunk).where(SearchChunk.case_id == case, SearchChunk.embedding.is_not(None))) == 3


@pytest.mark.asyncio
async def test_removing_a_cases_personal_data_removes_its_index(live_settings, scratch_unit):
    factory, store, models = get_session_factory(live_settings), MemoryStore(), FakeModels()
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            case_id, _ = await _document(session, store, scratch_unit, None, filename="b.pdf", values={"employee_code": DNI}, text="Boleta")
            await index_case(session, store, models, case_id)
            case = await session.get(Case, case_id)
            await retention.anonymize_case(session, store, case, reason="suprimido", actor="test", role="admin", channel="api")
            assert await session.scalar(select(func.count()).select_from(SearchChunk).where(SearchChunk.case_id == case_id)) == 0
            assert await search(session, models, DNI) == []
            assert await index_case(session, store, models, case_id) == 0, "an anonymized case is not indexed again"


@pytest.mark.asyncio
async def test_the_list_says_where_it_matched_and_searching_is_recorded(live_settings, scratch_unit):
    factory, store = get_session_factory(live_settings), MemoryStore()
    with tenancy.acting_for(scratch_unit):
        async with factory() as session:
            case, doc = await _document(session, store, scratch_unit, None, filename="boleta.pdf", values={"employee_code": DNI}, text=f"Código {DNI}")
            await index_case(session, store, FakeModels(), case)
            users = UserRepository(session)
            for role in ("operador", "visor"):
                await users.create(name=f"Busca {role}", email=f"test-busca-{role}-{scratch_unit}@example.com", password_hash=hash_password(_PASSWORD), role=role)
            await session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            async def login(role: str) -> dict[str, str]:
                r = await client.post("/auth/login", json={"email": f"test-busca-{role}-{scratch_unit}@example.com", "password": _PASSWORD})
                return {"Authorization": f"Bearer {r.json()['access_token']}"}

            operador, visor = await login("operador"), await login("visor")
            assert (await client.get("/documents", headers=visor, params={"q": DNI})).status_code == 403
            body = (await client.get("/documents", headers=operador, params={"q": DNI})).json()
            assert body["total"] == 1 and body["documents"][0]["id"] == str(doc)
            assert body["documents"][0]["match"] == {"where": "valores", "page": None}
            assert DNI not in str(body), "where it matched, never what it says"
            listed = (await client.get("/documents", headers=operador)).json()
            assert listed["total"] == 1 and listed["documents"][0]["match"] is None
        with tenancy.acting_for(scratch_unit):
            async with factory() as session:
                assert await session.scalar(select(func.count()).select_from(DataAccess).where(DataAccess.action == "buscar")) == 1
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email.like(f"test-busca-%-{scratch_unit}@example.com")))
            await session.commit()
