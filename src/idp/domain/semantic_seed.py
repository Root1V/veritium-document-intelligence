"""Seed semantic catalog v1, derived from the 12 typed schemas in
``domain/schemas/``. Published automatically as version 1 when the
``semantic_catalog_versions`` table is empty (see
``persistence.repositories.SemanticCatalogRepository.ensure_seed``).

Only fields with an unambiguous cross-document meaning are mapped. Left
unmapped on purpose, because mapping them would create false conflicts:
- loan amounts on the payment schedule, credit summary and account
  statement — they can describe an *existing* debt (e.g. one being
  subrogated), not the credit requested in this case;
- ``loan_application.monthly_income`` — not stated whether gross or net;
- ``authorization_letter.loan_amount`` and ``insurance_disclosure.loan_amount``
  — requested vs approved is not stated;
- email_correspondence — sender/recipient roles vary per email.
"""

from __future__ import annotations

from idp.domain.semantic import FieldMapping, SemanticAttribute, SemanticCatalog, SemanticEntity, SemanticRole

_DNI_FORMAT = "value.matches('^[0-9]{8}$')"
_RUC_FORMAT = "value.matches('^(10|15|17|20)[0-9]{9}$')"

_ENTITIES = [
    SemanticEntity(key="persona", name="Persona", definition="Persona natural que participa en el expediente."),
    SemanticEntity(key="empleador", name="Empleador", definition="Empresa o entidad empleadora de una persona."),
    SemanticEntity(key="ingreso", name="Ingreso", definition="Ingresos laborales periódicos de una persona."),
    SemanticEntity(key="credito", name="Crédito", definition="El crédito que se solicita o aprueba en este expediente."),
]

_ROLES = [
    SemanticRole(key="titular", name="Titular", definition="Titular o solicitante del crédito."),
    SemanticRole(key="conyuge", name="Cónyuge", definition="Cónyuge del titular, cuando el proceso lo requiere."),
    SemanticRole(key="aval", name="Aval", definition="Persona que garantiza el crédito."),
    SemanticRole(key="asesor", name="Asesor", definition="Asesor o promotor de la entidad que gestiona la solicitud; nunca es el titular."),
    SemanticRole(key="expediente", name="Expediente", definition="Datos del propio expediente, no de una persona (p. ej. el crédito solicitado)."),
]

_ATTRIBUTES = [
    SemanticAttribute(key="persona.dni", name="DNI", definition="Documento Nacional de Identidad peruano (8 dígitos).", data_type="string", comparison="identifier", format_cel=_DNI_FORMAT, pii_class="personal"),
    SemanticAttribute(key="persona.carnet_extranjeria", name="Carné de extranjería", definition="Número del carné de extranjería emitido por Migraciones.", data_type="string", comparison="identifier", pii_class="personal"),
    SemanticAttribute(key="persona.nombre_completo", name="Nombre completo", definition="Nombres y apellidos de la persona, en cualquier orden.", data_type="string", comparison="person_name", pii_class="personal"),
    SemanticAttribute(key="persona.nombres", name="Nombres", definition="Nombre(s) de pila.", data_type="string", comparison="person_name", pii_class="personal"),
    SemanticAttribute(key="persona.apellido_paterno", name="Apellido paterno", definition="Primer apellido.", data_type="string", comparison="person_name", pii_class="personal"),
    SemanticAttribute(key="persona.apellido_materno", name="Apellido materno", definition="Segundo apellido.", data_type="string", comparison="person_name", pii_class="personal"),
    SemanticAttribute(key="persona.fecha_nacimiento", name="Fecha de nacimiento", definition="Fecha de nacimiento de la persona.", data_type="date", comparison="date", pii_class="personal"),
    SemanticAttribute(key="persona.nacionalidad", name="Nacionalidad", definition="Nacionalidad declarada en el documento de identidad.", data_type="string", comparison="text"),
    SemanticAttribute(key="persona.estado_civil", name="Estado civil", definition="Estado civil declarado.", data_type="string", comparison="text", pii_class="personal"),
    SemanticAttribute(key="persona.email", name="Correo electrónico", definition="Correo electrónico de contacto.", data_type="string", comparison="text", pii_class="personal"),
    SemanticAttribute(key="persona.telefono", name="Teléfono", definition="Teléfono de contacto (solo dígitos).", data_type="string", comparison="identifier", pii_class="personal"),
    SemanticAttribute(key="persona.direccion", name="Dirección", definition="Domicilio declarado.", data_type="string", comparison="text", pii_class="personal"),
    SemanticAttribute(key="persona.codigo_empleado", name="Código de empleado", definition="Código del trabajador en la planilla del empleador (p. ej. AIRHSP).", data_type="string", comparison="identifier", pii_class="personal"),
    SemanticAttribute(key="empleador.razon_social", name="Razón social", definition="Nombre de la empresa o entidad empleadora.", data_type="string", comparison="company_name"),
    SemanticAttribute(key="empleador.ruc", name="RUC", definition="Registro Único de Contribuyentes del empleador (11 dígitos).", data_type="string", comparison="identifier", format_cel=_RUC_FORMAT),
    SemanticAttribute(key="ingreso.bruto_mensual", name="Ingreso bruto mensual", definition="Total de ingresos del periodo antes de descuentos.", data_type="number", comparison="number", unit="PEN", tolerance=0.01, pii_class="sensitive"),
    SemanticAttribute(key="ingreso.descuentos_mensuales", name="Descuentos mensuales", definition="Total de descuentos del periodo.", data_type="number", comparison="number", unit="PEN", tolerance=0.01, pii_class="sensitive"),
    SemanticAttribute(key="ingreso.neto_mensual", name="Ingreso neto mensual", definition="Lo que la persona recibe en el periodo después de descuentos.", data_type="number", comparison="number", unit="PEN", tolerance=0.01, pii_class="sensitive"),
    SemanticAttribute(key="credito.monto_solicitado", name="Monto solicitado", definition="Importe del crédito solicitado en este expediente.", data_type="number", comparison="number", unit="PEN", tolerance=0.005),
    SemanticAttribute(key="credito.monto_aprobado", name="Monto aprobado", definition="Importe aprobado por la entidad (puede diferir del solicitado).", data_type="number", comparison="number", unit="PEN", tolerance=0.005),
    SemanticAttribute(key="credito.plazo_meses", name="Plazo (meses)", definition="Número de meses o cuotas del crédito.", data_type="integer", comparison="number", tolerance=0.0),
    SemanticAttribute(key="credito.cuota_mensual", name="Cuota mensual", definition="Importe de la cuota mensual del crédito.", data_type="number", comparison="number", unit="PEN", tolerance=0.01),
]


def _m(document_type: str, field_path: str | list[str], attribute: str, role: str = "titular") -> FieldMapping:
    return FieldMapping(document_type=document_type, field_path=field_path, attribute=attribute, role=role)


def _split_name(document_type: str, first: str, paternal: str, maternal: str, role: str = "titular") -> list[FieldMapping]:
    return [
        _m(document_type, first, "persona.nombres", role),
        _m(document_type, paternal, "persona.apellido_paterno", role),
        _m(document_type, maternal, "persona.apellido_materno", role),
        _m(document_type, [first, paternal, maternal], "persona.nombre_completo", role),
    ]


_MAPPINGS = [
    # payslip
    _m("payslip", "employee_name", "persona.nombre_completo"),
    _m("payslip", "employee_code", "persona.codigo_empleado"),
    _m("payslip", "employer_name", "empleador.razon_social"),
    _m("payslip", "gross_pay", "ingreso.bruto_mensual"),
    _m("payslip", "total_deductions", "ingreso.descuentos_mensuales"),
    _m("payslip", "net_pay", "ingreso.neto_mensual"),
    # insurance_disclosure
    *_split_name("insurance_disclosure", "insured_first_name", "insured_paternal_surname", "insured_maternal_surname"),
    _m("insurance_disclosure", "insured_dni", "persona.dni"),
    # loan_application
    *_split_name("loan_application", "applicant_first_name", "applicant_paternal_surname", "applicant_maternal_surname"),
    _m("loan_application", "applicant_dni", "persona.dni"),
    _m("loan_application", "date_of_birth", "persona.fecha_nacimiento"),
    _m("loan_application", "email", "persona.email"),
    _m("loan_application", "phone_mobile", "persona.telefono"),
    _m("loan_application", "address", "persona.direccion"),
    _m("loan_application", "employment_center", "empleador.razon_social"),
    _m("loan_application", "employment_ruc", "empleador.ruc"),
    _m("loan_application", "loan_amount_requested", "credito.monto_solicitado", "expediente"),
    _m("loan_application", "loan_term_months", "credito.plazo_meses", "expediente"),
    _m("loan_application", "approved_amount", "credito.monto_aprobado", "expediente"),
    _m("loan_application", "loan_officer_name", "persona.nombre_completo", "asesor"),
    # loan_approval_remittance
    *_split_name("loan_approval_remittance", "applicant_first_name", "applicant_paternal_surname", "applicant_maternal_surname"),
    _m("loan_approval_remittance", "applicant_dni", "persona.dni"),
    _m("loan_approval_remittance", "email", "persona.email"),
    _m("loan_approval_remittance", "phone_mobile", "persona.telefono"),
    _m("loan_approval_remittance", "requested_amount", "credito.monto_solicitado", "expediente"),
    _m("loan_approval_remittance", "monthly_installment", "credito.cuota_mensual", "expediente"),
    # authorization_letter
    _m("authorization_letter", "client_name", "persona.nombre_completo"),
    _m("authorization_letter", "client_dni", "persona.dni"),
    _m("authorization_letter", "company", "empleador.razon_social"),
    _m("authorization_letter", "monthly_installment", "credito.cuota_mensual", "expediente"),
    _m("authorization_letter", "loan_term_months", "credito.plazo_meses", "expediente"),
    # foreign_resident_id — the first person on the card is taken as the titular
    _m("foreign_resident_id", "persons[0].first_names", "persona.nombres"),
    _m("foreign_resident_id", ["persons[0].first_names", "persons[0].surnames"], "persona.nombre_completo"),
    _m("foreign_resident_id", "persons[0].foreigner_id_number", "persona.carnet_extranjeria"),
    _m("foreign_resident_id", "persons[0].nationality", "persona.nacionalidad"),
    _m("foreign_resident_id", "persons[0].date_of_birth", "persona.fecha_nacimiento"),
    _m("foreign_resident_id", "persons[0].marital_status", "persona.estado_civil"),
    # loan_payment_schedule — identity only (see module docstring)
    _m("loan_payment_schedule", "client_name", "persona.nombre_completo"),
    _m("loan_payment_schedule", "client_dni", "persona.dni"),
    # credit_summary — identity only
    _m("credit_summary", "member_name", "persona.nombre_completo"),
    _m("credit_summary", "member_dni", "persona.dni"),
    _m("credit_summary", "member_phone", "persona.telefono"),
    # account_statement — identity only
    _m("account_statement", "member_name", "persona.nombre_completo"),
    _m("account_statement", "member_dni", "persona.dni"),
    # debt_subrogation_authorization
    _m("debt_subrogation_authorization", "client_name", "persona.nombre_completo"),
    _m("debt_subrogation_authorization", "client_dni", "persona.dni"),
    _m("debt_subrogation_authorization", "client_address", "persona.direccion"),
    _m("debt_subrogation_authorization", "client_phone", "persona.telefono"),
    _m("debt_subrogation_authorization", "client_email", "persona.email"),
    _m("debt_subrogation_authorization", "new_loan_amount", "credito.monto_solicitado", "expediente"),
    # debt_capacity_calculation
    _m("debt_capacity_calculation", "client_name", "persona.nombre_completo"),
    _m("debt_capacity_calculation", "client_dni", "persona.dni"),
    _m("debt_capacity_calculation", "net_income", "ingreso.neto_mensual"),
    _m("debt_capacity_calculation", "requested_amount", "credito.monto_solicitado", "expediente"),
    _m("debt_capacity_calculation", "requested_monthly_installment", "credito.cuota_mensual", "expediente"),
    _m("debt_capacity_calculation", "term_months", "credito.plazo_meses", "expediente"),
]


def seed_catalog() -> SemanticCatalog:
    return SemanticCatalog(entities=_ENTITIES, attributes=_ATTRIBUTES, roles=_ROLES, mappings=_MAPPINGS)
