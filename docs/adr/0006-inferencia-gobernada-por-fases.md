# ADR-0006 · Inferencia gobernada, por fases

**Estado:** aceptada · 2026-10-07 · depende de `VRT-AEON-003`, `VRT-SYN-003`, `VRT-SYN-002`

## Contexto
- **axonium** es el SDK obligatorio para invocar inferencia local en prometheus.
- synaptum define dos rutas (`roadmap.md:156`):
  - **autónoma** (Axonium-Python): "dev, notebooks, tests";
  - **gobernada** (synaptum → aeon-modelgw, que usa Axonium-Go, → prometheus): la de producción, con presupuestos y costo por run.
- Hoy la ruta gobernada no transporta tools, `response_format` ni imágenes, y no aplica presupuestos en `/v1/chat/completions`.

## Decisión
- Toda la inferencia pasa por **`InferencePort`**, y los agentes por **`AgentRuntime`**.
- **F1:** adaptador **autónomo**: todo el tráfico de modelo (llamadas sueltas con `synaptum.generate()` y el agente de extracción) pasa por synaptum con `LocalGateway` + `AxoniumModel` → prometheus. Así el paso a producción es solo cambiar el `Gateway` (acordado en `VRT-SYN-001`/`003`).
- **Producción (VRT-56):** adaptador **gobernado** obligatorio. Se solicitan en paralelo a aeon A-2 y A-3, y a synaptum S-4 a S-8.
- Se reemplazan `openai` + `instructor`. La salida estructurada la resuelve synaptum: `generate()` con validación Pydantic y re-pregunta mostrando el error (S-2/S-6).

## Consecuencias
- No se pasa a producción sin la ruta gobernada.
- **Precisión de aeon (`VRT-AEON-003`):** el transporte aeon-modelgw → Axonium-Go → prometheus **ya está entregado**. Faltan A-2 (fidelidad del adaptador) y A-3 (presupuestos e idempotencia en `/v1/chat/completions`, con las cabeceras `X-Aeon-Run-Id` / `X-Aeon-Agent-Manifest-Ref` / `Idempotency-Key`), más S-4…S-8 de synaptum.
- **Credenciales en producción:** Veritium solo tiene su bearer de aeon (`AEON_CALLER_TOKEN_FILE`); las credenciales de prometheus viven únicamente en modelgw.
- El cambio de ruta es por configuración: el dominio no se toca.
