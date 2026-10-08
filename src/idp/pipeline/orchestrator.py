"""Case run orchestrator (VRT-25): one evaluation of a case. Extracts the
documents added since the previous run (parse -> segment -> classify ->
extract -> persist), then re-validates the whole case in a single unified
pass (all 6 rule categories plus the semantic consistency check, since
cross-document rules need every document's fields), then per-field review
routing.

Still a plain async function invoked from FastAPI ``BackgroundTasks`` — the
durable, parallel executor on aeon replaces this entrypoint in VRT-26
(ADR-0003). Each stage is OTEL-traced and the state lives in the DB, so that
promotion is mechanical, not a rewrite.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from idp.classification.classifier import needs_review as classification_needs_review
from idp.config import Settings
from idp.domain.document_types import DocumentType
from idp.domain.envelope import Extracted
from idp.domain.request_payload import RequestInputPayload
from idp.domain.schemas import schema_for
from idp.domain.schemas.generic import GenericSchema
from idp.domain.process_profile import ProcessProfileDefinition
from idp.domain.semantic import SemanticCatalog
from idp.domain.semantic_resolution import ConsolidatedView, DocumentExtraction, resolve_case
from idp.extraction.agentic.loop import ExtractionIncomplete
from idp.observability.otel import traced_stage
from idp.parsing.base import ParserBackend
from idp.parsing.docling_backend import DoclingBackend
from idp.parsing.paddleocr_backend import PaddleOCRBackend
from idp.persistence.models import ValidationIssue as ValidationIssueModel
from idp.persistence.repositories import (
    CaseRepository,
    CaseRunRepository,
    DocumentRepository,
    ExtractionRepository,
    ReviewRepository,
    SemanticCatalogRepository,
    TypeSuggestionRepository,
    ValidationRepository,
    ValidationRuleRepository,
)
from idp.parsing.normalize import ParsedDocument, slice_by_pages
from idp.pipeline.case_evaluation import apply_binding, profile_definition, refresh_conditions, refresh_verdict, rules_for_profile
from idp.pipeline.provenance import build_provenance
from idp.webhooks.events import emit_run_finished
from idp.pipeline.stages import classify_document, extract_document, parse_document, segment_document, suggest_type
from idp.review.queue import enqueue_review_items
from idp.review.routing import find_review_candidates
from idp.storage.object_store import ObjectStore
from idp.validation.base import ValidationRule
from idp.validation.context import DocumentFields, ValidationContext
from idp.validation.engine import run_validation
from idp.validation.ports import ExternalSystemPort, ReferenceDataPort
from idp.validation.rules.batch_rules import DuplicateDocumentIdentifier, EmployeeNameCrossDocumentMatch
from idp.validation.rules.external_system_rules import InsurancePolicyVerifiedExternally
from idp.validation.rules.generic import DataDrivenRule
from idp.validation.rules.reference_data_rules import EmployeeCodeExistsInReferenceData, EmployeeNameExistsInReferenceData
from idp.validation.rules.request_input_rules import ExpectedEmployeeCodeMatches
from idp.validation.rules.self_rules import DniFormatValid, PayslipArithmeticConsistency
from idp.validation.rules.semantic_rules import SemanticAttributeConsistency


def make_parser_backend(settings: Settings) -> ParserBackend:
    if settings.parser_backend == "docling":
        return DoclingBackend(settings)
    return PaddleOCRBackend(settings)


def _hardcoded_rules(settings: Settings) -> list[ValidationRule]:
    """The registered hand-written rule set — one or more concrete rules
    per of the 6 categories (5 from the user's feedback plus intra-document
    'self' checks). Extracted to its own function so
    hardcoded_rule_metadata() can read rule_id/category off each real
    instance instead of duplicating those strings by hand elsewhere."""
    return [
        PayslipArithmeticConsistency(),
        DniFormatValid("insurance_disclosure", "insured_dni"),
        DniFormatValid("authorization_letter", "client_dni"),
        DniFormatValid("loan_application", "applicant_dni"),
        DniFormatValid("loan_approval_remittance", "applicant_dni"),
        DniFormatValid("loan_payment_schedule", "client_dni"),
        DniFormatValid("credit_summary", "member_dni"),
        DniFormatValid("account_statement", "member_dni"),
        DniFormatValid("debt_subrogation_authorization", "client_dni"),
        DniFormatValid("debt_capacity_calculation", "client_dni"),
        ExpectedEmployeeCodeMatches(),
        DuplicateDocumentIdentifier(),
        EmployeeNameCrossDocumentMatch(settings),
        EmployeeCodeExistsInReferenceData(),
        EmployeeNameExistsInReferenceData(settings),
        InsurancePolicyVerifiedExternally(),
        SemanticAttributeConsistency(),
    ]


HARDCODED_RULE_DESCRIPTIONS: dict[str, str] = {
    "self.payslip_arithmetic_consistency": "Verifica que el neto de la boleta de pago sea igual al bruto menos los descuentos totales (con una pequeña tolerancia).",
    "self.insurance_disclosure_dni_format_valid": "Verifica que el DNI del asegurado tenga el formato peruano valido (8 digitos numericos).",
    "self.authorization_letter_dni_format_valid": "Verifica que el DNI del cliente en la carta de autorizacion tenga formato valido (8 digitos).",
    "self.loan_application_dni_format_valid": "Verifica que el DNI del solicitante en la solicitud de prestamo tenga formato valido (8 digitos).",
    "self.loan_approval_remittance_dni_format_valid": "Verifica que el DNI del solicitante en la remesa de aprobacion tenga formato valido (8 digitos).",
    "self.loan_payment_schedule_dni_format_valid": "Verifica que el DNI del cliente en el cronograma de pagos tenga formato valido (8 digitos).",
    "self.credit_summary_dni_format_valid": "Verifica que el DNI del miembro en el resumen crediticio tenga formato valido (8 digitos).",
    "self.account_statement_dni_format_valid": "Verifica que el DNI del miembro en el estado de cuenta tenga formato valido (8 digitos).",
    "self.debt_subrogation_authorization_dni_format_valid": "Verifica que el DNI del cliente en la autorizacion de subrogacion de deuda tenga formato valido (8 digitos).",
    "self.debt_capacity_calculation_dni_format_valid": "Verifica que el DNI del cliente en el calculo de capacidad de endeudamiento tenga formato valido (8 digitos).",
    "request_input.expected_employee_code_matches": "Compara el codigo de empleado extraido de la boleta contra el codigo esperado ingresado al subir la solicitud.",
    "batch.duplicate_identifier": "Detecta si el mismo identificador (codigo de empleado o numero de poliza) aparece duplicado entre documentos del mismo tipo dentro de la misma solicitud.",
    "batch.employee_name_matches_insured_name": "Compara el nombre del empleado en la boleta contra el nombre del asegurado en la declaracion de seguro de la misma solicitud (tolera variaciones de formato; escala a un LLM en casos ambiguos).",
    "reference_data.employee_code_exists": "Verifica que el codigo de empleado extraido exista en la tabla interna de empleados de referencia.",
    "reference_data.employee_name_matches_reference": "Cuando no hay codigo de empleado, busca el nombre extraido contra la tabla de empleados de referencia por similitud (tolera variaciones; escala a un LLM en casos ambiguos).",
    "semantic.attribute_consistency": "Compara entre documentos del expediente cada atributo del catalogo semantico que comparten (DNI, nombre, ingresos, empleador, montos), segun el tipo de comparacion del atributo.",
    "external_system.insurance_policy_verified": "Verifica el numero de poliza contra un sistema externo de la aseguradora — hoy es un stub sin integracion real, ver /document-types u otra documentacion sobre 'sistema externo'.",
}


def hardcoded_rule_metadata(settings: Settings) -> list[tuple[str, str, str]]:
    """(rule_id, category, description) for every hardcoded rule — used by
    GET/POST /validation-rules/toggles/* so that endpoint never has to
    hand-duplicate the exact rule_id strings from validation/rules/*.py."""
    return [(r.rule_id, r.category.value, HARDCODED_RULE_DESCRIPTIONS.get(r.rule_id, "")) for r in _hardcoded_rules(settings)]


async def build_default_rules(settings: Settings, session: AsyncSession) -> list[ValidationRule]:
    """The full rule set: the hardcoded instances (minus any rule_id an
    operator has toggled off via a kind="toggle" row), plus one
    DataDrivenRule per active kind="cel" row. Async because it now needs a
    DB round-trip — a rule activated/disabled between batch runs must be
    picked up on the very next run, not only at process start."""
    hardcoded = [r for r in _hardcoded_rules(settings) if r.rule_id not in await ValidationRuleRepository(session).list_disabled_toggle_rule_ids()]

    data_driven: list[ValidationRule] = []
    for row in await ValidationRuleRepository(session).list_active_cel_rules():
        try:
            data_driven.append(DataDrivenRule(row))
        except Exception:
            # Defense in depth — shouldn't happen given PATCH/activate
            # already validate that the CEL compiles, but a corrupted row
            # must not take down the whole batch.
            continue

    return hardcoded + data_driven


async def resolve_semantic_view(
    session: AsyncSession, documents: list[DocumentFields], *, catalog_version: int | None = None
) -> ConsolidatedView | None:
    """The case's consolidated semantic view (VRT-23) over every document
    that reached extraction — against ``catalog_version`` when the case's
    profile pins one, else the latest published catalog. None when there is
    no catalog to resolve against."""
    repo = SemanticCatalogRepository(session)
    if catalog_version is not None:
        row = await repo.get_version(catalog_version)
        if row is None:
            return None
        catalog, version = SemanticCatalog.model_validate(row.definition), row.version
    else:
        active = await repo.load_active()
        if active is None:
            return None
        catalog, version = active
    extractions = [
        DocumentExtraction(document_id=d.document_id, document_type=d.document_type, payload=d.payload)
        for d in documents
        if d.payload is not None
    ]
    return resolve_case(catalog, extractions, catalog_version=version)


def flatten_top_level_fields(instance: BaseModel) -> dict[str, Any]:
    """Unwraps top-level ``Extracted[T]`` leaves into plain field_path ->
    value for ``ValidationContext`` — rules never need to know about the
    citation envelope. Phase 0's rule set only references top-level fields;
    nested line items (e.g. ``concepts``) are not flattened."""
    out: dict[str, Any] = {}
    for name in type(instance).model_fields:
        value = getattr(instance, name)
        if isinstance(value, Extracted):
            out[name] = value.value
    return out


async def _classify_and_extract(
    *,
    settings: Settings,
    session: AsyncSession,
    parsed: ParsedDocument,
    document_id: uuid.UUID,
    case_id: uuid.UUID,
    parser_backend_name: str,
    document_repo: DocumentRepository,
    extraction_repo: ExtractionRepository,
    type_suggestion_repo: TypeSuggestionRepository,
) -> DocumentFields | None:
    # Each stage transition commits immediately (not batched with the rest
    # of the document's processing) so a concurrent GET /batches/{id} poll
    # observes the pipeline actually advancing, not a single jump from
    # "uploaded" to "extracted" once the whole document is done — see the
    # frontend's PipelineStepper, the reason this granularity exists.
    await document_repo.set_status(document_id, "classifying")
    await session.commit()
    classification = await asyncio.to_thread(classify_document, settings, parsed, document_id=str(document_id))

    await document_repo.set_classification(
        document_id,
        document_type=classification.document_type.value,
        confidence=classification.confidence,
        reasoning=classification.reasoning,
        needs_review=classification_needs_review(settings, classification),
    )
    await document_repo.set_status(document_id, "extracting")
    await session.commit()

    outcome = await asyncio.to_thread(
        extract_document, settings, parsed, classification.document_type, document_id=str(document_id)
    )

    if outcome.schema_instance is None:
        await document_repo.mark_needs_review(document_id)
        await document_repo.set_status(document_id, "needs_review")
        return None

    await extraction_repo.save(
        document_id=document_id,
        schema_version="1.0",
        payload=outcome.schema_instance.model_dump(mode="json"),
        parser_backend=parser_backend_name,
        extraction_method=outcome.extraction_method,
    )
    await document_repo.set_status(document_id, "extracted")

    if classification.document_type == DocumentType.GENERIC and isinstance(outcome.schema_instance, GenericSchema):
        await _suggest_type_if_promising(
            settings,
            outcome.schema_instance,
            document_id=document_id,
            case_id=case_id,
            type_suggestion_repo=type_suggestion_repo,
        )

    return DocumentFields(
        document_id=document_id,
        document_type=classification.document_type.value,
        fields=flatten_top_level_fields(outcome.schema_instance),
        payload=outcome.schema_instance.model_dump(mode="json"),
    )


async def _suggest_type_if_promising(
    settings: Settings,
    generic_result: GenericSchema,
    *,
    document_id: uuid.UUID,
    case_id: uuid.UUID,
    type_suggestion_repo: TypeSuggestionRepository,
) -> None:
    """Best-effort: a document that fell into 'generic' gets one more LLM
    pass asking whether its content looks like a stable, recurring
    business document type worth promoting (see
    classification/type_discovery.py). A failure or a 'not promotable'
    verdict here must never affect the document's own processing — this is
    a side-channel signal for a human, not part of the document's pipeline
    result."""
    try:
        proposal = await asyncio.to_thread(suggest_type, settings, generic_result, document_id=str(document_id))
    except Exception:
        return
    if not proposal.is_promotable or not proposal.suggested_type_name:
        return
    await type_suggestion_repo.create(
        document_id=document_id,
        case_id=case_id,
        suggested_type_name=proposal.suggested_type_name,
        suggested_display_name=proposal.suggested_display_name or proposal.suggested_type_name,
        rationale=proposal.rationale,
        fields=[f.model_dump() for f in proposal.fields],
    )


async def _process_uploaded_file(
    *,
    settings: Settings,
    session: AsyncSession,
    backend: ParserBackend,
    case_id: uuid.UUID,
    document_id: uuid.UUID,
    storage_key: str,
    filename: str,
    object_store: ObjectStore,
    document_repo: DocumentRepository,
    extraction_repo: ExtractionRepository,
    type_suggestion_repo: TypeSuggestionRepository,
) -> list[DocumentFields]:
    """Parses the raw physical upload once, then checks whether it actually
    bundles more than one logical document (segmentation.detect_segments —
    see that module's docstring for why this exists: a real 7-page PDF
    turned out to be an email + a payment schedule + contract T&Cs + an
    account statement, and forcing all of it through one classify->extract
    pass timed out repeatedly).

    The common case (one segment covering the whole file) processes in
    place using the ``document_id`` row already created at upload time — no
    new rows, no behavior change for anything that worked before
    segmentation existed. Extra segments each get their own child Document
    row (same storage_key — it's the same physical file, no re-upload) and
    are classified/extracted independently, with per-segment failure
    isolation matching the existing per-document isolation in
    ``process_case_run``."""
    await document_repo.set_status(document_id, "parsing")
    await session.commit()
    file_bytes = await asyncio.to_thread(object_store.get, storage_key)
    parsed = await asyncio.to_thread(parse_document, settings, backend, file_bytes, filename, document_id=str(document_id))
    segments = await asyncio.to_thread(segment_document, settings, parsed, document_id=str(document_id))

    if len(segments) <= 1:
        fields = await _classify_and_extract(
            settings=settings,
            session=session,
            parsed=parsed,
            document_id=document_id,
            case_id=case_id,
            parser_backend_name=backend.name,
            document_repo=document_repo,
            extraction_repo=extraction_repo,
            type_suggestion_repo=type_suggestion_repo,
        )
        return [fields] if fields is not None else []

    await document_repo.set_status(document_id, "segmented")
    await session.commit()
    all_fields: list[DocumentFields] = []
    for segment in segments:
        sliced = slice_by_pages(parsed, segment.start_page, segment.end_page)
        child = await document_repo.create_child(
            case_id=case_id,
            parent_document_id=document_id,
            storage_key=storage_key,
            original_filename=f"{filename}#p{segment.start_page}-{segment.end_page}",
            page_start=segment.start_page,
            page_end=segment.end_page,
        )
        await session.commit()
        try:
            fields = await _classify_and_extract(
                settings=settings,
                session=session,
                parsed=sliced,
                document_id=child.id,
                case_id=case_id,
                parser_backend_name=backend.name,
                document_repo=document_repo,
                extraction_repo=extraction_repo,
                type_suggestion_repo=type_suggestion_repo,
            )
        except ExtractionIncomplete:
            await document_repo.mark_needs_review(child.id)
            await document_repo.set_status(child.id, "needs_review")
            fields = None
        except Exception:
            await document_repo.set_status(child.id, "failed")
            fields = None
        if fields is not None:
            all_fields.append(fields)
    return all_fields


async def process_case_run(
    *,
    settings: Settings,
    session: AsyncSession,
    case_id: uuid.UUID,
    run_id: uuid.UUID,
    object_store: ObjectStore,
    reference_data: ReferenceDataPort,
    external_system: ExternalSystemPort,
) -> None:
    """One evaluation of a case. Only documents still ``uploaded`` (added
    since the previous run) go through extraction; validation then covers
    every document of the case that has an extraction, so cross-document
    and semantic checks see the case as it is now. The previous run's
    issues are superseded, never deleted."""
    case_repo = CaseRepository(session)
    run_repo = CaseRunRepository(session)
    document_repo = DocumentRepository(session)
    extraction_repo = ExtractionRepository(session)
    validation_repo = ValidationRepository(session)
    review_repo = ReviewRepository(session)
    type_suggestion_repo = TypeSuggestionRepository(session)

    case = await case_repo.get(case_id)
    run = await run_repo.get(run_id)
    if case is None or run is None:
        raise ValueError(f"case run not found: case={case_id} run={run_id}")

    profile_version = case.profile_version
    definition = profile_definition(case)
    rules = rules_for_profile(await build_default_rules(settings, session), definition)
    provenance = build_provenance(settings, profile_version=profile_version, rules=rules)
    await run_repo.mark_running(run, provenance=provenance)
    await case_repo.set_status(case_id, "processing")
    await session.commit()

    try:
        backend = make_parser_backend(settings)
        request_payload = RequestInputPayload(data=case.request_input_payload or {})

        for document in [d for d in case.documents if d.status == "uploaded"]:
            with traced_stage("process_document", case_id=str(case_id), document_id=str(document.id)):
                try:
                    await _process_uploaded_file(
                        settings=settings,
                        session=session,
                        backend=backend,
                        case_id=case_id,
                        document_id=document.id,
                        storage_key=document.storage_key,
                        filename=document.original_filename,
                        object_store=object_store,
                        document_repo=document_repo,
                        extraction_repo=extraction_repo,
                        type_suggestion_repo=type_suggestion_repo,
                    )
                except ExtractionIncomplete:
                    await document_repo.mark_needs_review(document.id)
                    await document_repo.set_status(document.id, "needs_review")
                except Exception:
                    # A single document's failure (e.g. the configured
                    # LLM/VLM endpoint being unreachable) must not leave the
                    # whole case stuck in "processing" — mark this document
                    # failed and keep going. The OTEL span records the error.
                    await document_repo.set_status(document.id, "failed")
            await session.commit()

        all_fields = await case_document_fields(document_repo, case_id)
        catalog_version = profile_version.semantic_catalog_version if profile_version is not None else None
        semantic_view = await resolve_semantic_view(session, all_fields, catalog_version=catalog_version)
        run.provenance = {**provenance, "semantic_catalog_version": semantic_view.catalog_version if semantic_view else None}
        await validation_repo.supersede_active(case_id)
        await session.commit()

        for current in all_fields:
            await _validate_document(
                settings=settings,
                session=session,
                current=current,
                siblings=[f for f in all_fields if f.document_id != current.document_id],
                case_id=case_id,
                run_id=run.id,
                rules=rules,
                definition=definition,
                request_payload=request_payload,
                reference_data=reference_data,
                external_system=external_system,
                semantic_view=semantic_view,
                document_repo=document_repo,
                validation_repo=validation_repo,
                review_repo=review_repo,
            )

        await refresh_conditions(session, case, run, semantic_view, definition)
        await refresh_verdict(session, case_id, run=run)
        await case_repo.set_status(case_id, "completed")
        await run_repo.mark_finished(run, status="completed")
        emit_run_finished(session, case, run)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        run = await run_repo.get(run_id)
        if run is not None:
            await run_repo.mark_finished(run, status="failed", error=f"{type(exc).__name__}: {exc}")
        await case_repo.set_status(case_id, "failed")
        failed_case = await case_repo.get(case_id)
        if run is not None and failed_case is not None:
            emit_run_finished(session, failed_case, run)
        await session.commit()
        raise


async def case_document_fields(document_repo: DocumentRepository, case_id: uuid.UUID) -> list[DocumentFields]:
    """Every document of the case that has an extraction, rebuilt from the
    stored payload — the same shape extraction returns, whether the
    document was extracted in this run or an earlier one."""
    out: list[DocumentFields] = []
    for document in await document_repo.list_for_case(case_id):
        if document.extraction is None or document.document_type is None:
            continue
        payload = document.extraction.payload
        fields = {name: env["value"] for name, env in payload.items() if isinstance(env, dict) and "value" in env}
        out.append(DocumentFields(document_id=document.id, document_type=document.document_type, fields=fields, payload=payload))
    return out


async def _validate_document(
    *,
    settings: Settings,
    session: AsyncSession,
    current: DocumentFields,
    siblings: list[DocumentFields],
    case_id: uuid.UUID,
    run_id: uuid.UUID,
    rules: list[ValidationRule],
    definition: ProcessProfileDefinition | None,
    request_payload: RequestInputPayload,
    reference_data: ReferenceDataPort,
    external_system: ExternalSystemPort,
    semantic_view: ConsolidatedView | None,
    document_repo: DocumentRepository,
    validation_repo: ValidationRepository,
    review_repo: ReviewRepository,
) -> None:
    await document_repo.set_status(current.document_id, "validating")
    await session.commit()
    context = ValidationContext(
        case_id=case_id,
        current_document=current,
        sibling_documents=siblings,
        request_payload=request_payload,
        reference_data=reference_data,
        external_system=external_system,
        semantic_view=semantic_view,
    )
    try:
        with traced_stage("validate", case_id=str(case_id), document_id=str(current.document_id)):
            results = [apply_binding(r, definition) for r in await run_validation(rules, context)]

        for result in results:
            if not result.passed:
                await validation_repo.save_issue(
                    ValidationIssueModel(
                        document_id=current.document_id,
                        case_id=case_id,
                        case_run_id=run_id,
                        rule_id=result.rule_id,
                        category=result.category.value,
                        field_path=result.field_path,
                        severity=result.severity.value if result.severity else "warning",
                        message=result.message,
                        expected=_jsonable(result.expected),
                        actual=_jsonable(result.actual),
                        confidence=result.confidence,
                        confidence_method=result.confidence_method.value,
                        explanation=result.explanation,
                    )
                )

        document = await document_repo.get(current.document_id)
        if document is not None and document.extraction is not None:
            schema_instance = schema_for(current.document_type).model_validate(document.extraction.payload)
            threshold = definition.thresholds.field_confidence_min if definition and definition.thresholds.field_confidence_min is not None else settings.review_confidence_threshold
            candidates = find_review_candidates(schema_instance, results, confidence_threshold=threshold)
            # A re-evaluation must not ask a human twice about the same field.
            new_candidates = [c for c in candidates if not await review_repo.has_item_for_field(current.document_id, c.field_path)]
            if new_candidates:
                await enqueue_review_items(review_repo, document_id=current.document_id, candidates=new_candidates)
                await document_repo.mark_needs_review(current.document_id)
            pending = new_candidates or await review_repo.has_pending_for_document(current.document_id)
            await document_repo.set_status(current.document_id, "needs_review" if pending else "completed")
    except Exception:
        # One document's validation blowing up (e.g. a reference-data or
        # external-system port erroring) must not lose the rest of the case.
        await document_repo.set_status(current.document_id, "failed")
    await session.commit()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return {"value": value} if not isinstance(value, dict) else value
    return {"value": str(value)}
