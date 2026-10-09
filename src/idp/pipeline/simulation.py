"""What-if simulation and shadow mode (VRT-44): decide a case with a
candidate profile version — its checklist, rule bindings (draft rules it
binds included: that is what would be published), semantic catalog and
thresholds — from what was already extracted, writing nothing about the
case. ``run_what_if`` does it over the profile's past cases; ``run_shadows``
does it after every real run while a shadow simulation is on."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from idp.config import Settings
from idp.domain.calibration import Calibration, field_key
from idp.domain.completeness import CaseDocument, evaluate_checklist
from idp.domain.process_profile import ProcessProfileDefinition
from idp.domain.request_payload import RequestInputPayload
from idp.domain.simulation import difference
from idp.domain.verdict import CaseVerdict, FindingInput, OpenCondition, VerdictInputs, decide
from idp.persistence.db import get_session_factory
from idp.persistence.models import Case, ProcessProfile, ProcessProfileVersion, ReviewItem, Simulation, SimulationResult
from idp.persistence.repositories import (
    CalibrationRepository,
    CaseConditionRepository,
    CaseRepository,
    DocumentRepository,
    DocumentTypeRepository,
    ReferenceDataRepository,
    ValidationRuleRepository,
)
from idp.pipeline.case_evaluation import apply_binding, rules_for_profile
from idp.pipeline.orchestrator import (
    build_default_rules,
    case_document_fields,
    display_names,
    extraction_schema,
    load_semantic_catalog,
    resolve_semantic_view,
)
from idp.review.routing import find_review_candidates
from idp.validation.base import ValidationRule
from idp.validation.context import ValidationContext
from idp.validation.engine import run_validation
from idp.validation.ports import StubExternalSystemPort
from idp.validation.rules.generic import DataDrivenRule
from idp.validation.rules.semantic_rules import format_rules

log = logging.getLogger(__name__)
_running: set[uuid.UUID] = set()


async def candidate_rules(settings: Settings, session: AsyncSession, version: ProcessProfileVersion) -> list[ValidationRule]:
    definition = ProcessProfileDefinition.model_validate(version.definition)
    rules = await build_default_rules(settings, session)
    active = {r.rule_id for r in rules}
    bound = definition.bound_rule_ids()
    for row in await ValidationRuleRepository(session).list_all(kind="cel"):
        if row.rule_id in bound and row.rule_id not in active and row.status not in ("rejected", "disabled"):
            try:
                rules.append(DataDrivenRule(row))
            except Exception:
                continue  # a draft whose CEL does not compile cannot run
    loaded = await load_semantic_catalog(session, version.semantic_catalog_version)
    return rules_for_profile(rules + (format_rules(loaded[0]) if loaded else []), definition)


async def simulate_case(
    settings: Settings, session: AsyncSession, case: Case, version: ProcessProfileVersion, rules: list[ValidationRule], calibration: Calibration | None
) -> CaseVerdict:
    definition = ProcessProfileDefinition.model_validate(version.definition)
    document_repo = DocumentRepository(session)
    fields = await case_document_fields(document_repo, case.id)
    view = await resolve_semantic_view(session, fields, catalog_version=version.semantic_catalog_version)
    request_payload = RequestInputPayload(data=case.request_input_payload or {})
    documents = await document_repo.list_for_case(case.id)
    items = list(await session.scalars(select(ReviewItem).where(ReviewItem.document_id.in_([d.id for d in documents]))))
    reviewed = {(i.document_id, i.field_path) for i in items}
    pending = {i.document_id for i in items if i.status == "pending"}
    type_catalog = await DocumentTypeRepository(session).load_catalog()
    threshold = definition.thresholds.field_confidence_min if definition.thresholds.field_confidence_min is not None else settings.review_confidence_threshold
    by_id = {d.id: d for d in documents}
    loaded = await load_semantic_catalog(session, version.semantic_catalog_version)
    names = display_names(loaded[0] if loaded else None, type_catalog)

    findings: list[FindingInput] = []
    for current in fields:
        context = ValidationContext(
            case_id=case.id,
            current_document=current,
            sibling_documents=[f for f in fields if f.document_id != current.document_id],
            request_payload=request_payload,
            reference_data=ReferenceDataRepository(session),
            external_system=StubExternalSystemPort(),
            semantic_view=view,
            names=names,
        )
        results = [apply_binding(r, definition) for r in await run_validation(rules, context)]
        findings += [FindingInput(rule_id=r.rule_id, message=r.message, document_id=current.document_id) for r in results if not r.passed]
        # The candidate's threshold may send other fields to a person.
        document = by_id.get(current.document_id)
        if document is not None and document.extraction is not None:
            instance = extraction_schema(type_catalog, current.document_type, document.extraction.schema_version).model_validate(document.extraction.payload)
            calibrate = (lambda path, raw: calibration.calibrated(field_key(current.document_type, path), raw)) if calibration else None
            candidates = find_review_candidates(instance, results, confidence_threshold=threshold, calibrate=calibrate)
            if any((current.document_id, c.field_path) not in reviewed for c in candidates):
                pending.add(current.document_id)

    waived = {k for k, c in (await CaseConditionRepository(session).latest_by_key(case.id)).items() if c.status == "waived"}
    open_conditions = [
        OpenCondition(key=o.item.key, label=o.item.label, kind="missing_document" if o.item.document_type is not None else "missing_evidence")
        for o in evaluate_checklist(
            definition, [CaseDocument(document_id=d.id, document_type=d.document_type, status=d.status) for d in documents], view, case.request_input_payload or {}
        )
        if o.applicable and not o.satisfied and o.item.key not in waived
    ]
    return decide(
        VerdictInputs(
            open_conditions=open_conditions,
            findings=findings,
            pending_review_document_ids=pending,
            failed_document_ids={d.id for d in documents if d.status == "failed"},
        ),
        definition,
    )


async def _decide(
    settings: Settings, session: AsyncSession, case: Case, version: ProcessProfileVersion, rules: list[ValidationRule], calibration: Calibration | None
) -> tuple[CaseVerdict | None, str | None]:
    """One case's simulated decision, or why it could not be made. A
    savepoint keeps one case's failure from spoiling the rest."""
    try:
        async with session.begin_nested():
            return await simulate_case(settings, session, case, version, rules, calibration), None
    except Exception as exc:
        log.warning("simulation of case %s failed: %s", case.id, exc)
        return None, f"{type(exc).__name__}: {exc}"[:2000]


async def _record(session: AsyncSession, simulation: Simulation, case: Case, run_id: uuid.UUID | None, verdict: CaseVerdict | None, error: str | None) -> None:
    simulated = [r.model_dump(mode="json") for r in verdict.reasons] if verdict else []
    diff = difference(case.verdict_reasons, simulated)
    values = {
        "id": uuid.uuid4(),
        "simulation_id": simulation.id,
        "case_id": case.id,
        "case_run_id": run_id,
        "actual_verdict": case.verdict,
        "simulated_verdict": verdict.decision if verdict else None,
        "added_reasons": diff.added_reasons if verdict else [],
        "removed_reasons": diff.removed_reasons if verdict else [],
        "error": error,
    }
    update = {k: v for k, v in values.items() if k not in ("id", "simulation_id", "case_id")}
    await session.execute(
        pg_insert(SimulationResult).values(**values).on_conflict_do_update(index_elements=["simulation_id", "case_id"], set_={**update, "created_at": datetime.now(UTC)})
    )


async def _loaded(session: AsyncSession, simulation_id: uuid.UUID) -> Simulation | None:
    return await session.get(Simulation, simulation_id, populate_existing=True)


async def run_what_if(settings: Settings, simulation_id: uuid.UUID) -> None:
    """Re-decides the profile's latest past cases with the candidate."""
    if simulation_id in _running:
        return
    _running.add(simulation_id)
    factory = get_session_factory(settings)
    try:
        async with factory() as session:
            simulation = await _loaded(session, simulation_id)
            if simulation is None or simulation.status not in ("pending", "running"):
                return
            simulation.status = "running"
            await session.commit()
            version = await session.get(ProcessProfileVersion, simulation.profile_version_id)
            assert version is not None
            stmt = (
                select(Case.id)
                .join(ProcessProfileVersion, ProcessProfileVersion.id == Case.profile_version_id)
                .join(ProcessProfile, ProcessProfile.id == ProcessProfileVersion.profile_id)
                .where(ProcessProfile.key == simulation.profile_key, Case.status == "completed", Case.verdict.is_not(None))
                .order_by(Case.created_at.desc())
                .limit(simulation.case_limit or 50)
            )
            case_ids = list((await session.scalars(stmt)).all())
            rules = await candidate_rules(settings, session, version)
            active = await CalibrationRepository(session).active()
            calibration = Calibration.model_validate(active.model) if active else None
            for case_id in case_ids:
                case = await CaseRepository(session).get(case_id)
                if case is None:
                    continue
                verdict, error = await _decide(settings, session, case, version, rules, calibration)
                await _record(session, simulation, case, None, verdict, error)
                await session.commit()
            simulation = await _loaded(session, simulation_id)
            assert simulation is not None
            simulation.status, simulation.finished_at = "completed", datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        async with factory() as session:
            simulation = await _loaded(session, simulation_id)
            if simulation is not None:
                simulation.status, simulation.error, simulation.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:2000], datetime.now(UTC)
                await session.commit()
        raise
    finally:
        _running.discard(simulation_id)


async def run_shadows(settings: Settings, case_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """After a real run: decide the case with every shadow candidate of its
    profile. A shadow never fails the real run; its error is recorded."""
    async with get_session_factory(settings)() as session:
        case = await CaseRepository(session).get(case_id)
        if case is None or case.profile_version is None:
            return
        shadows = list(
            (await session.scalars(select(Simulation).where(Simulation.kind == "shadow", Simulation.status == "running", Simulation.profile_key == case.profile_version.profile.key))).all()
        )
        if not shadows:
            return
        active = await CalibrationRepository(session).active()
        calibration = Calibration.model_validate(active.model) if active else None
        for simulation in shadows:
            version = await session.get(ProcessProfileVersion, simulation.profile_version_id)
            if version is None:
                continue
            verdict, error = await _decide(settings, session, case, version, await candidate_rules(settings, session, version), calibration)
            await _record(session, simulation, case, run_id, verdict, error)
            await session.commit()
