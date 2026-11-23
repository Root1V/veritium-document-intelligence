"""Intra-document deterministic checks — arithmetic/date/format consistency
within a single document. Never an LLM call, per the cross-cutting
'deterministic core' principle: correctness-critical math stays in plain
Python."""

from __future__ import annotations

import re

from idp.validation.base import ConfidenceMethod, RuleCategory, Severity, ValidationResult, ValidationRule
from idp.validation.context import ValidationContext

_TOLERANCE = 0.01


class PayslipArithmeticConsistency(ValidationRule):
    rule_id = "self.payslip_arithmetic_consistency"
    reads = frozenset({"gross_pay", "total_deductions", "net_pay"})
    category = RuleCategory.SELF

    def applies_when(self, context: ValidationContext) -> bool:
        return context.current_document.document_type == "payslip"

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        fields = context.current_document.fields
        gross = fields.get("gross_pay")
        deductions = fields.get("total_deductions")
        net = fields.get("net_pay")

        if gross is None or deductions is None or net is None:
            return ValidationResult(
                rule_id=self.rule_id,
                category=self.category,
                passed=True,
                message="Faltan datos de la boleta para verificar el neto; regla omitida.",
                confidence=1.0,
                confidence_method=ConfidenceMethod.DETERMINISTIC,
                explanation="gross_pay, total_deductions o net_pay ausente en la extraccion.",
            )

        expected_net = round(gross - deductions, 2)
        passed = abs(expected_net - net) <= _TOLERANCE
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.ERROR,
            field_path="net_pay",
            message="El neto a pagar es igual al bruto menos los descuentos."
            if passed
            else f"El neto a pagar ({net:,.2f}) no es igual al bruto menos los descuentos ({expected_net:,.2f}).",
            expected=expected_net,
            actual=net,
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"gross_pay({gross}) - total_deductions({deductions}) = {expected_net} vs net_pay extraido = {net} (tolerancia {_TOLERANCE}).",
        )


_MONTHS = {m: i for i, m in enumerate(("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"), start=1)} | {"sep": 9, "jan": 1, "apr": 4, "aug": 8, "dec": 12}


def _yymmdd(text: object) -> str | None:
    """A printed date ('05 Ene 1979', '05/01/1979', '1979-01-05') as the machine-readable line writes it."""
    s = str(text or "").strip().lower()
    if m := re.fullmatch(r"(\d{1,2})[\s./-]*([a-z]{3})[a-z.]*[\s./-]*(\d{4})", s):
        day, month, year = int(m[1]), _MONTHS.get(m[2]), m[3]
    elif m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s):
        day, month, year = int(m[1]), int(m[2]), m[3]
    elif m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        day, month, year = int(m[3]), int(m[2]), m[1]
    else:
        return None
    return f"{year[2:]}{month:02d}{day:02d}" if month else None


def _digits(value: object) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


class MachineReadableZoneChecks(ValidationRule):
    """VRT-116: the check digits of the line with «<» (ICAO 9303) confirm it
    was read whole, and its number and birth date must be the ones extracted.
    Its expiry is not compared: on Peruvian foreign-resident cards the printed
    «Vencimiento» is another date (measured on the bench, 2026-11-23)."""

    rule_id = "self.machine_readable_zone"
    reads = frozenset({"persons", "machine_readable_zones"})
    category = RuleCategory.SELF

    def applies_when(self, context: ValidationContext) -> bool:
        return bool((context.current_document.payload or {}).get("machine_readable_zones"))

    async def evaluate(self, context: ValidationContext) -> ValidationResult:
        payload = context.current_document.payload or {}
        persons = payload.get("persons") or []
        problems: list[tuple[str | None, str]] = []  # (field_path, what)
        for zone in payload["machine_readable_zones"]:
            where = f"pág. {zone['page'] + 1}" if zone.get("page") is not None else "el documento"
            index = next((i for i, p in enumerate(persons) if zone["number"] in _digits((p.get("foreigner_id_number") or {}).get("value"))), None)
            prefix = f"persons[{index}]." if index is not None else None
            if zone["failed"]:
                problems.append((prefix and f"{prefix}foreigner_id_number", f"la línea de lectura automática de {where} no cuadra con sus dígitos de control: se leyó mal o fue alterada"))
                continue
            if persons and index is None:
                problems.append((None, f"el número {zone['number']} de la línea de lectura automática de {where} no es el de ningún titular extraído"))
                continue
            if index is not None:
                birth = (persons[index].get("date_of_birth") or {}).get("value")
                if birth and _yymmdd(birth) not in (None, zone["birth"]):
                    problems.append((f"{prefix}date_of_birth", f"la fecha de nacimiento ({birth}) no es la de la línea de lectura automática de {where}"))
        passed = not problems
        return ValidationResult(
            rule_id=self.rule_id,
            category=self.category,
            passed=passed,
            severity=None if passed else Severity.WARNING,
            field_path=next((path for path, _ in problems if path), None),
            message="La línea de lectura automática cuadra con sus dígitos de control y con lo extraído."
            if passed
            else "; ".join(what for _, what in problems).capitalize() + ".",
            confidence=1.0,
            confidence_method=ConfidenceMethod.DETERMINISTIC,
            explanation=f"ICAO 9303: {len(payload['machine_readable_zones'])} línea(s) verificada(s).",
        )
