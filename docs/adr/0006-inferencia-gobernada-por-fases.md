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
- **F1:** adaptador **autónomo** (`AsyncAxonium` → prometheus; synaptum con `LocalGateway` + `AxoniumModel`).
- **Producción (VRT-56):** adaptador **gobernado** obligatorio. Se solicitan en paralelo a aeon A-2 y A-3, y a synaptum S-4 a S-8.
- Se reemplazan `openai` + `instructor`. La salida estructurada se resuelve con `response_format` + Pydantic + re-pregunta con el error.

## Consecuencias
- No se pasa a producción sin la ruta gobernada.
- El cambio de ruta es por configuración: el dominio no se toca.
