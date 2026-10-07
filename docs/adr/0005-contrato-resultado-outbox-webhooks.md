# ADR-0005 · Contrato de resultado v1, outbox transaccional y Standard Webhooks

**Estado:** aceptada · 2026-10-07

## Contexto
Los procesos que invocan a Veritium toman decisiones con su respuesta y se integran por distintos canales. Necesitan un resultado **estable** y notificaciones que **no se pierdan ni se dupliquen**.

## Decisión
- **Resultado canónico v1 (JSON)** en `GET /v1/cases/{id}/result`. Contiene:
  - veredicto y motivos, y condiciones;
  - `entities`, la vista semántica consolidada con la evidencia por fuente ([ADR-0007](0007-capa-semantica-ligera.md));
  - los documentos con `Extracted[T]`;
  - los hallazgos (regla, versión, severidad, evidencia);
  - la procedencia y las versiones de perfil y catálogo.

  Los demás formatos (YAML, Markdown, PDF, A2UI) se **derivan** de él.
- **Transactional outbox:** los eventos (tipos CloudEvents `pe.veritium.case.*`) se escriben en la misma transacción que el cambio de estado.
- **Webhooks** según la spec Standard Webhooks:
  - headers `webhook-id`, `webhook-timestamp` y `webhook-signature` (HMAC-SHA256 con rotación de claves);
  - backoff exponencial con jitter hasta ~3 días;
  - entrega *at-least-once* con idempotencia por `webhook-id`.
- Los despacha **Veritium**: es contrato de su dominio, no de aeon.

## Consecuencias
- Un cambio incompatible del contrato implica `v2`. Los campos nuevos opcionales no rompen.
- Los consumidores deben verificar la firma y deduplicar por `webhook-id`.
