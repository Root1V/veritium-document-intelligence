"""Self-check of an extraction draft (VRT-67): the document's own rules run
on the agent's draft, and the agent sees what fails before submitting."""

from __future__ import annotations

import asyncio

import pytest
from synaptum.testing.fake import calls

from idp.config import Settings
from idp.extraction.agentic.loop import run_agentic_extraction
from idp.extraction.agentic.prompts import build_system_prompt
from idp.domain.schemas.loan_application import LoanApplicationSchema
from idp.domain.schemas.payslip import PayslipSchema
from idp.domain.semantic_seed import seed_catalog
from idp.extraction.self_check import DraftChecker
from idp.llm import port
from idp.validation.rules.self_rules import PayslipArithmeticConsistency
from idp.validation.rules.semantic_rules import SemanticAttributeConsistency, format_rules
from tests.unit.test_agentic_extraction import PARSED, Boleta, Script, _tool_results


@pytest.mark.asyncio
async def test_the_documents_arithmetic_is_checked_on_the_draft_with_amounts_as_written():
    checker = DraftChecker([PayslipArithmeticConsistency()], None, "payslip", PayslipSchema)
    problems = await checker.check({"gross_pay": "4,000.00", "total_deductions": 500, "net_pay": "3,400.00"})
    assert problems == ["El neto a pagar (3,400.00) no es igual al bruto menos los descuentos (3,500.00)."]
    assert await checker.check({"gross_pay": "4,000.00", "total_deductions": 500, "net_pay": 3500}) == []
    envelopes = {"gross_pay": {"value": 4000, "page": 0}, "total_deductions": {"value": 500}, "net_pay": {"value": 3400, "confidence": 0.9}}
    assert len(await checker.check(envelopes)) == 1, "the schema's envelopes are read as their values"
    assert (await checker.check({"gross_pay": "cuatro mil", "total_deductions": 500, "net_pay": 3500}))[0].startswith("No se pudo revisar")


@pytest.mark.asyncio
async def test_each_attributes_format_comes_from_the_semantic_catalog():
    catalog = seed_catalog()
    checker = DraftChecker([*format_rules(catalog), SemanticAttributeConsistency()], catalog, "loan_application", LoanApplicationSchema)
    assert [r.rule_id for r in checker.rules] == [r.rule_id for r in format_rules(catalog)], "only the document's own rules (SELF)"
    (problem,) = await checker.check({"applicant_dni": "4228586"})
    assert problem.startswith("DNI sin formato válido") and "4228586" in problem
    assert await checker.check({"applicant_dni": "42285866"}) == []


class _Checker:
    async def check(self, draft):
        return ["El neto a pagar (2,400.00) no es igual al bruto menos los descuentos (2,500.00)."] if draft.get("neto") == 2400 else []


@pytest.mark.asyncio
async def test_the_agent_checks_its_draft_corrects_and_submits():
    script = Script(
        calls("check_draft", values={"empleado": "ANA PEREZ", "neto": 2400}),
        calls("read_text_region", id="c2", region_ids=[1]),
        calls("check_draft", id="c3", values={"empleado": "ANA PEREZ", "neto": 2500}),
        calls("submit", id="c4", empleado="ANA PEREZ", neto=2500.0),
    )
    settings = Settings(_env_file=None, extraction_max_turns=8)
    async with port.inference_lifespan(settings, model=script, models={"reasoning": "razonador", "vision": "vlm"}):
        result, trace = await asyncio.to_thread(
            lambda: run_agentic_extraction(settings, PARSED, Boleta, purpose="extract/payslip/v1", hint="Es una boleta.", checker=_Checker())  # type: ignore[arg-type]
        )
    assert result == Boleta(empleado="ANA PEREZ", neto=2500.0)
    assert "Problemas encontrados" in _tool_results(script.requests[1])[0]
    assert _tool_results(script.requests[3])[-1] == "Sin problemas."
    assert "check_draft" in (script.requests[0].system or "") and [t.tool_name for t in trace] == ["check_draft", "read_text_region", "check_draft"]


def test_without_a_checker_the_agent_has_neither_the_tool_nor_the_step():
    assert "check_draft" not in str(build_system_prompt("x", Boleta, PARSED))
    assert "check_draft" in str(build_system_prompt("x", Boleta, PARSED, self_check=True))
