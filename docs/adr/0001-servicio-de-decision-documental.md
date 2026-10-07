# ADR-0001 · Veritium es un servicio de decisión documental, no un motor de workflow

**Estado:** aceptada · 2026-10-07

## Contexto
Veritium (v0.3.0) analiza documentos sueltos subidos por un usuario. Distintos procesos de negocio (contratación en línea, backoffice, oficina, Riesgos, Legal) necesitan invocar la misma capacidad de comprensión y validación, y la mayoría ya tiene su propio orquestador (BPM, core, app).

## Decisión
Veritium gestiona el **expediente desde el punto de vista documental**: checklist, observaciones, revisión humana de documentos y un **veredicto accionable con evidencia** (continuar / revisión humana / devolver al cliente). El **flujo del negocio** (aprobar un crédito, asignar tareas comerciales, SLAs del proceso) lo orquesta el sistema que invoca a Veritium.

## Consecuencias
- Veritium se expone por API, eventos y webhooks. Su salida es un contrato estable ([ADR-0005](0005-contrato-resultado-outbox-webhooks.md)).
- La revisión humana es **documental**: corregir campos, dispensar condiciones. No hay tareas de negocio.
- Los items de UI ligados a documentos sueltos se absorben en la vista de expediente (VRT-15, 17–20 → `superseded`).
