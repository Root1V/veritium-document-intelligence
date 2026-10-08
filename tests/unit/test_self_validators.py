from __future__ import annotations

import pytest

from idp.validation.rules.self_rules import PayslipArithmeticConsistency
from tests.conftest import make_context, make_document_fields


@pytest.mark.asyncio
async def test_payslip_arithmetic_passes_on_real_fixture_values():
    # boleta_pagos1.png: 6618.00 - 2313.86 = 4304.14 (verified against the source image)
    fields = make_document_fields("payslip", {"gross_pay": 6618.00, "total_deductions": 2313.86, "net_pay": 4304.14})
    result = await PayslipArithmeticConsistency().evaluate(make_context(fields))
    assert result.passed
    assert result.confidence_method == "deterministic"


@pytest.mark.asyncio
async def test_payslip_arithmetic_fails_on_tampered_total():
    fields = make_document_fields("payslip", {"gross_pay": 6618.00, "total_deductions": 2313.86, "net_pay": 9999.00})
    result = await PayslipArithmeticConsistency().evaluate(make_context(fields))
    assert not result.passed
    assert result.severity == "error"
    assert result.field_path == "net_pay"


@pytest.mark.asyncio
async def test_payslip_arithmetic_skips_when_fields_missing():
    fields = make_document_fields("payslip", {"gross_pay": 6618.00})
    result = await PayslipArithmeticConsistency().evaluate(make_context(fields))
    assert result.passed
