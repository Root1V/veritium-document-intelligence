# ADR-0002 · Evolución por reemplazo progresivo; `Batch` pasa a `Case`

**Estado:** aceptada · 2026-10-07

## Contexto
El rediseño cambia la unidad de trabajo, pero v0.3.0 ya resuelve bien varias cosas: grounding citado `Extracted[T]`, motor de validación de 6 categorías, reglas CEL y descubrimiento de tipos. Reescribir desde cero tiraría esos diferenciadores y retrasaría tener algo funcionando de punta a punta.

## Decisión
- Evolucionar en el **mismo repo** con reemplazo progresivo (*strangler*). `v0.3.0` queda como tag de referencia.
- El agregado `Batch` pasa a ser **`Case`** (expediente): tabla `cases`, `documents.case_id`, más perfil, idempotencia, canal y veredicto.
- `/batches` y su SSE se mantienen como **alias** que crean y leen expedientes con el perfil integrado `ad-hoc`, de modo que el frontend actual sigue funcionando hasta su reemplazo (VRT-38).

## Consecuencias
- Una migración de esquema que renombra tabla y columna; los repositorios y las rutas se adaptan.
- Conviven por un tiempo dos superficies de API (`/batches` legado y `/v1/cases`). El legado se retira cuando el frontend migre.
