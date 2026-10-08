"""Engine-level tests (topological ordering, applies_when gating) — the
'known-bad synthetic fixture' case from the Fase 0 verification plan,
exercised through ``run_validation`` rather than calling a rule directly."""

from __future__ import annotations

import pytest

from idp.validation.engine import run_validation
from idp.validation.rules.self_rules import PayslipArithmeticConsistency
from tests.conftest import make_context, make_document_fields


@pytest.mark.asyncio
async def test_tampered_total_produces_validation_issue_via_engine():
    fields = make_document_fields("payslip", {"gross_pay": 6618.00, "total_deductions": 2313.86, "net_pay": 1.00})
    context = make_context(fields)
    results = await run_validation([PayslipArithmeticConsistency()], context)
    assert any(not r.passed and r.field_path == "net_pay" for r in results)


@pytest.mark.asyncio
async def test_rule_that_does_not_apply_is_skipped_entirely():
    # A format rule with no value of its attribute in this document must not run.
    from idp.domain.semantic_seed import seed_catalog
    from idp.validation.rules.semantic_rules import format_rules

    fields = make_document_fields("payslip", {"gross_pay": 100.0, "total_deductions": 10.0, "net_pay": 90.0})
    context = make_context(fields)
    results = await run_validation(format_rules(seed_catalog()), context)
    assert results == []
