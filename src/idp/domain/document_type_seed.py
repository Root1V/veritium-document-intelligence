"""Seed of the document type catalog (VRT-32): version 1 of each built-in
type, derived from the Pydantic schemas in ``domain/schemas`` plus the
texts below. Published once into ``document_type_versions`` at startup;
from then on the database is the source, and a change to a type is a new
version through ``/v1/document-types`` — editing this module changes
nothing for an existing database."""

from __future__ import annotations

from idp.domain.document_type_catalog import DocumentTypeDefinition, definition_from_model
from idp.domain.document_types import DocumentType
from idp.domain.schemas import SCHEMA_BY_DOCUMENT_TYPE

DISPLAY_NAMES: dict[DocumentType, str] = {
    DocumentType.PAYSLIP: "Boleta de pago",
    DocumentType.INSURANCE_DISCLOSURE: "Declaración personal de seguros",
    DocumentType.AUTHORIZATION_LETTER: "Carta de autorización",
    DocumentType.LOAN_APPLICATION: "Solicitud de préstamo",
    DocumentType.LOAN_APPROVAL_REMITTANCE: "Remisión de aprobación de préstamo",
    DocumentType.FOREIGN_RESIDENT_ID: "Carné de extranjería",
    DocumentType.EMAIL_CORRESPONDENCE: "Correo electrónico",
    DocumentType.LOAN_PAYMENT_SCHEDULE: "Cronograma de pagos",
    DocumentType.CREDIT_SUMMARY: "Resumen de crédito",
    DocumentType.ACCOUNT_STATEMENT: "Estado de cuenta",
    DocumentType.DEBT_SUBROGATION_AUTHORIZATION: "Autorización de subrogación de deudas",
    DocumentType.DEBT_CAPACITY_CALCULATION: "Cálculo de capacidad de endeudamiento",
}

# What each type is — the classifier reads these to choose between types.
DESCRIPTIONS: dict[DocumentType, str] = {
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
}

# Hints for the extraction agent, prepended to its system prompt.
HINTS: dict[DocumentType, str] = {
    DocumentType.PAYSLIP: "Es una boleta de pago (payslip) de una empresa peruana.",
    DocumentType.INSURANCE_DISCLOSURE: (
        "Es un documento de seguro (p. ej. seguro de desgravamen) asociado a un prestamo. "
        "El nombre del titular suele estar dividido en cajas/regiones separadas ('Apellido Paterno', "
        "'Apellido Materno', 'Nombre') — cada una va en su propio campo del esquema "
        "(insured_first_name/insured_paternal_surname/insured_maternal_surname), no los combines en un "
        "solo campo."
    ),
    DocumentType.AUTHORIZATION_LETTER: (
        "Es una carta de autorizacion (p. ej. autorizacion de descuento por planilla) en la que una "
        "persona autoriza a un tercero (empleador, banco) a actuar en su nombre o a descontarle dinero "
        "de sus ingresos para amortizar un prestamo."
    ),
    DocumentType.LOAN_APPLICATION: (
        "Es un formulario extenso de solicitud de prestamo/convenio bancario, con multiples secciones "
        "(datos del prestamo, datos personales, laborales, del conyuge, patrimonio, referencias, "
        "evaluacion del banco) — puede tener varias paginas y menciona varias personas distintas (el "
        "solicitante, y por separado un asesor/coordinador de ventas del banco). Presta atencion cuidadosa "
        "a la descripcion (\"description\") de cada campo en el esquema objetivo mas abajo — varios campos "
        "de este formulario son facilmente confundibles entre si (p. ej. datos del solicitante vs. del "
        "asesor, o campos con nombre similar en secciones distintas del documento) y su descripcion "
        "aclara exactamente a cual corresponden."
    ),
    DocumentType.LOAN_APPROVAL_REMITTANCE: (
        "Es una ficha/registro breve de UNA sola seccion que resume el estado de aprobacion de un caso de "
        "prestamo (p. ej. 'Estado: APROBADO - RRHH'), con datos de contacto del solicitante, el importe "
        "solicitado, la cuota mensual y la fecha de aprobacion. NO tiene secciones de datos laborales, "
        "conyuge, patrimonio ni referencias — no lo confundas con loan_application."
    ),
    DocumentType.FOREIGN_RESIDENT_ID: (
        "Es una copia escaneada de uno o mas 'Carnet de Extranjeria' (documento de identidad de residente "
        "extranjero en el Peru). El documento puede contener el registro de MAS DE UNA persona (p. ej. una "
        "pareja) — extrae una entrada en la lista 'persons' por cada persona distinta que encuentres, no "
        "mezcles los datos de dos personas en una sola entrada."
    ),
    DocumentType.EMAIL_CORRESPONDENCE: (
        "Es un correo electronico (a menudo reenviado entre personal de banco/empleador) encontrado dentro "
        "del paquete de documentos. Su contenido de negocio puede ser cualquier cosa — no asumas de "
        "antemano de que trata (puede ser una consulta de deuda, una aprobacion, una solicitud, etc.). "
        "Extrae los metadatos universales del correo (remitente, destinatario, fecha, asunto) como campos "
        "fijos, y cualquier dato de negocio relevante mencionado en el cuerpo (nombres, DNIs, montos, "
        "entidades) como entradas libres en 'key_facts'."
    ),
    DocumentType.LOAN_PAYMENT_SCHEDULE: (
        "Es un 'Cronograma de Pagos' (tabla de amortizacion de un credito) emitido por una entidad "
        "financiera: cabecera con datos del cliente y del credito (monto, tasa, plazo), seguida de una "
        "tabla con una fila por cuota (numero, fecha, monto, interes, capital, saldo). Agrupa TODAS las "
        "celdas de una misma fila de la tabla al leerlas, para armar cada entrada de 'installments' con "
        "sus columnas correctas."
    ),
    DocumentType.CREDIT_SUMMARY: (
        "Es una ficha resumen de UNA sola pagina que muestra un credito activo de un socio de una "
        "caja/cooperativa a modo de vistazo (monto, plazo, cuota, tasa, estado) — NO tiene la tabla de "
        "cuotas fila por fila (eso es loan_payment_schedule); no lo confundas con ese tipo."
    ),
    DocumentType.ACCOUNT_STATEMENT: (
        "Es un 'Estado de Cuenta' de un socio de una caja/cooperativa: datos de identidad del socio, saldo "
        "de aportes, y el saldo/avance del producto (credito o ahorro) principal asociado."
    ),
    DocumentType.DEBT_SUBROGATION_AUTHORIZATION: (
        "Es una 'AUTORIZACION PARA LA SUBROGACION DE DEUDA DE OTROS BANCOS' — el cliente autoriza a un banco "
        "a cancelar deudas (prestamos y/o tarjetas de credito) que mantiene en OTRAS entidades financieras, "
        "financiado por un prestamo nuevo. Su contenido central es una tabla 'DETALLE DE LA DEUDA A "
        "SUBROGAR' con filas de PRESTAMOS y de TARJETAS DE CREDITO — extrae SOLO las filas con datos reales "
        "(entidad y monto), ignora las filas vacias de la plantilla. No lo confundas con authorization_letter "
        "(autorizacion de descuento por planilla), que no tiene esta tabla de deudas."
    ),
    DocumentType.DEBT_CAPACITY_CALCULATION: (
        "Es la salida de una calculadora interna de capacidad de endeudamiento ('Calculadora'/'Kontigo'): "
        "evalua si un cliente califica para un credito nuevo dado su buro de riesgo, ingresos, descuentos y "
        "deuda BBVA existente por producto. Tiene varias secciones numeradas de ingresos/descuentos "
        "('Ingreso 1', 'Descuento 1', etc.) y una seccion de deuda existente por producto (Tarjeta, "
        "CCONVPLAN, CPLD, etc.) — agrupalas en 'income_lines' y 'existing_debts' respectivamente, una "
        "entrada por cada linea con datos reales."
    ),
}


def seed_definitions() -> list[DocumentTypeDefinition]:
    return [
        definition_from_model(
            SCHEMA_BY_DOCUMENT_TYPE[t],
            key=t.value,
            display_name=DISPLAY_NAMES[t],
            description=DESCRIPTIONS[t],
            extraction_hint=HINTS.get(t, ""),
        )
        for t in DocumentType
        if t != DocumentType.GENERIC
    ]
