"""Document-type classification — new relative to the PoC, which had no
notion of document-level type (only PaddleOCR's built-in per-*region* labels).
A single structured-output call produces a routing decision; nothing
downstream needs to know how that decision was made."""

from __future__ import annotations

from pydantic import BaseModel, Field

from idp.config import Settings
from idp.domain.document_types import DocumentType
from idp.llm.port import structured
from idp.observability.otel import traced_llm_call
from idp.parsing.normalize import ParsedDocument

TYPE_DESCRIPTIONS = {
    DocumentType.PAYSLIP: "boleta de pago — detalle de ingresos/descuentos de un empleado en un periodo",
    DocumentType.INSURANCE_DISCLOSURE: "declaracion personal de seguros (p. ej. seguro de desgravamen) asociada a un prestamo",
    DocumentType.AUTHORIZATION_LETTER: (
        "carta de autorizacion breve (1 pagina, formato carta) en la que una persona autoriza a un tercero "
        "(empleador, banco) a actuar en su nombre o a descontar dinero de sus ingresos — p. ej. autorizacion "
        "de descuento por planilla para amortizar un prestamo personal. No es un formulario con secciones "
        "ni casillas de seleccion."
    ),
    DocumentType.LOAN_APPLICATION: (
        "solicitud de prestamo o convenio bancario — un FORMULARIO extenso (varias secciones marcadas con "
        "letras A, B, C..., casillas de seleccion, campos para llenar) que recopila datos del prestamo, "
        "datos personales del solicitante, datos laborales, del conyuge, patrimonio, referencias y una "
        "seccion de evaluacion/aprobacion del banco. Se distingue de authorization_letter por ser un "
        "formulario de captura de datos multi-seccion, no una carta corta de autorizacion."
    ),
    DocumentType.LOAN_APPROVAL_REMITTANCE: (
        "ficha o registro breve de UNA sola seccion que resume el estado de aprobacion de un caso de "
        "prestamo (p. ej. 'Estado: APROBADO - RRHH'), con DNI, nombre, contacto, importe solicitado, cuota "
        "mensual y fecha de aprobacion. A diferencia de loan_application, no tiene secciones de datos "
        "laborales, conyuge, patrimonio ni referencias."
    ),
    DocumentType.FOREIGN_RESIDENT_ID: (
        "copia escaneada de uno o mas 'Carnet de Extranjeria' (documento de identidad de residente "
        "extranjero en el Peru) — muestra apellidos, nombres, nacionalidad, fecha de nacimiento, numero de "
        "carne, numero de pasaporte y fechas de inscripcion/emision/vencimiento. Puede incluir el registro "
        "de mas de una persona."
    ),
    DocumentType.EMAIL_CORRESPONDENCE: (
        "correo electronico (a menudo reenviado entre personal de banco/empleador) encontrado dentro del "
        "paquete de documentos — tiene remitente, destinatario, fecha, y contenido de negocio variable que "
        "puede ser cualquier cosa (una consulta de deuda, una aprobacion, una solicitud, etc.)."
    ),
    DocumentType.LOAN_PAYMENT_SCHEDULE: (
        "'Cronograma de Pagos' — tabla de amortizacion de un credito emitida por una entidad financiera: "
        "cabecera con datos del cliente/credito (monto, tasa, plazo) seguida de una tabla con una fila por "
        "cuota (numero, fecha, monto, interes, capital, saldo)."
    ),
    DocumentType.CREDIT_SUMMARY: (
        "ficha resumen de UNA sola pagina de un credito activo de un socio de una caja/cooperativa a modo "
        "de vistazo (monto, plazo, cuota, tasa, estado) — sin tabla de cuotas fila por fila."
    ),
    DocumentType.ACCOUNT_STATEMENT: (
        "'Estado de Cuenta' de un socio de una caja/cooperativa — identidad del socio, saldo de aportes, y "
        "saldo/avance del producto (credito o ahorro) principal."
    ),
    DocumentType.DEBT_SUBROGATION_AUTHORIZATION: (
        "'AUTORIZACION PARA LA SUBROGACION DE DEUDA DE OTROS BANCOS' — el cliente autoriza a un banco a "
        "cancelar deudas (prestamos y/o tarjetas de credito) mantenidas en OTRAS entidades financieras, "
        "financiado por un prestamo nuevo. Se distingue por una tabla 'DETALLE DE LA DEUDA A SUBROGAR' con "
        "filas de prestamos y tarjetas de credito — no tiene relacion con descuento por planilla."
    ),
    DocumentType.DEBT_CAPACITY_CALCULATION: (
        "salida de una calculadora interna de capacidad de endeudamiento ('Calculadora'/'Kontigo') — evalua "
        "si un cliente califica para un credito nuevo dado su buro de riesgo, ingresos, descuentos y deuda "
        "BBVA existente por producto (Tarjeta, CCONVPLAN, CPLD, etc.), con secciones numeradas de "
        "ingresos/descuentos."
    ),
    DocumentType.GENERIC: "cualquier otro documento que no encaje claramente en los tipos anteriores",
}
_TYPE_LIST = "\n".join(f"- {t.value}: {desc}" for t, desc in TYPE_DESCRIPTIONS.items())

_SYSTEM_PROMPT = f"""Eres un clasificador de documentos empresariales. Dado el texto \
extraido de un documento, determina su tipo. Los tipos validos son:
{_TYPE_LIST}

Si el documento no encaja claramente en ninguno de los tipos especificos, clasifica como generic.
Responde con el tipo, tu confianza (0-1) y una breve justificacion."""


class ClassificationResult(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


def classify(settings: Settings, parsed: ParsedDocument) -> ClassificationResult:
    text_excerpt = parsed.full_text[:4000]
    with traced_llm_call(role="reasoning", model=settings.reasoning_model):
        result = structured(
            purpose="classify",
            role="reasoning",
            output=ClassificationResult,
            instructions=_SYSTEM_PROMPT,
            task=f"Texto del documento:\n\n{text_excerpt}",
        )
    return result


def needs_review(settings: Settings, result: ClassificationResult) -> bool:
    return result.confidence < settings.classification_confidence_threshold or result.document_type == DocumentType.GENERIC
