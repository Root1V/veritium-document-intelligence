"""The built-in types' schemas in code: the source of version 1 of the
document type catalog (``domain/document_type_seed.py``, VRT-32). At
runtime a type's schema comes from the catalog, compiled per version."""

from __future__ import annotations

from pydantic import BaseModel

from idp.domain.document_types import DocumentType
from idp.domain.schemas.account_statement import AccountStatementSchema
from idp.domain.schemas.authorization_letter import AuthorizationLetterSchema
from idp.domain.schemas.credit_summary import CreditSummarySchema
from idp.domain.schemas.debt_capacity_calculation import DebtCapacityCalculationSchema
from idp.domain.schemas.debt_subrogation_authorization import DebtSubrogationAuthorizationSchema
from idp.domain.schemas.email_correspondence import EmailCorrespondenceSchema
from idp.domain.schemas.foreign_resident_id import ForeignResidentIdSchema
from idp.domain.schemas.generic import GenericSchema
from idp.domain.schemas.insurance_disclosure import InsuranceDisclosureSchema
from idp.domain.schemas.loan_application import LoanApplicationSchema
from idp.domain.schemas.loan_approval_remittance import LoanApprovalRemittanceSchema
from idp.domain.schemas.loan_payment_schedule import LoanPaymentScheduleSchema
from idp.domain.schemas.payslip import PayslipSchema

SCHEMA_BY_DOCUMENT_TYPE: dict[DocumentType, type[BaseModel]] = {
    DocumentType.PAYSLIP: PayslipSchema,
    DocumentType.INSURANCE_DISCLOSURE: InsuranceDisclosureSchema,
    DocumentType.AUTHORIZATION_LETTER: AuthorizationLetterSchema,
    DocumentType.LOAN_APPLICATION: LoanApplicationSchema,
    DocumentType.LOAN_APPROVAL_REMITTANCE: LoanApprovalRemittanceSchema,
    DocumentType.FOREIGN_RESIDENT_ID: ForeignResidentIdSchema,
    DocumentType.EMAIL_CORRESPONDENCE: EmailCorrespondenceSchema,
    DocumentType.LOAN_PAYMENT_SCHEDULE: LoanPaymentScheduleSchema,
    DocumentType.CREDIT_SUMMARY: CreditSummarySchema,
    DocumentType.ACCOUNT_STATEMENT: AccountStatementSchema,
    DocumentType.DEBT_SUBROGATION_AUTHORIZATION: DebtSubrogationAuthorizationSchema,
    DocumentType.DEBT_CAPACITY_CALCULATION: DebtCapacityCalculationSchema,
    DocumentType.GENERIC: GenericSchema,
}

