# Roadmap

Índice por fase. El detalle de cada item está en [docs/roadmap.md](docs/roadmap.md) y las decisiones de arquitectura en [docs/adr/](docs/adr/).
Estados: `done` · `todo` · `blocked` (espera a otro equipo) · `superseded` (absorbido por otro item).

## F0 — Base v0.3.0

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-01 | Pipeline agéntico de documentos | done | Ingesta → parsing → clasificación → extracción con grounding citado → validación (6 categorías) → revisión humana. |
| VRT-02 | Segmentación + tipos de documento | done | Divide un PDF bundle en documentos lógicos; 12 `DocumentType` tipados + `generic`. |
| VRT-03 | Descubrimiento automático de tipos | done | El LLM propone tipos nuevos cuando un documento cae en `generic`; un humano decide. |
| VRT-04 | Módulo web (frontend) | done | Login JWT, dashboard, carga, lotes, visor con bounding boxes, revisión, tipos. |
| VRT-05 | Vista de auditoría | done | `/audit` — historial de correcciones. |
| VRT-06 | Browser de documentos | done | `/documents` con filtros combinados. |
| VRT-07 | Métrica de tiempo ahorrado | done | Tarjeta en el dashboard, con supuesto configurable. |
| VRT-08 | Roles de usuario | done | admin / operador / visor, con enforcement en cada endpoint. |
| VRT-09 | Pipeline visual en tiempo real | done | Progreso por etapa y documento en `/batches/:id`. |
| VRT-10 | Server-Sent Events | done | Reemplaza el polling de 2 s por push del servidor. |
| VRT-11 | Búsqueda de texto libre | done | En `/documents`, sobre el nombre de archivo y el contenido extraído. |
| VRT-12 | Editor de sugerencias de tipo | done | Editar el borrador del LLM antes de aceptar o rechazar un tipo nuevo. |
| VRT-13 | Vista de auditoría de validación | done | `/validation` — observaciones de validación cruzando documentos. |
| VRT-14 | Motor de reglas configurables (CEL) | done | `/validation-rules` — crear, editar, activar y desactivar reglas sin tocar código. |
| VRT-15 | UI de Integraciones | superseded | Absorbido por VRT-60. |
| VRT-16 | Corregir layout del visor de documento | done | El PDF ya no se superpone al panel de campos extraídos. |
| VRT-17 | Corregir bounding box resaltado | superseded | Absorbido por VRT-38. |
| VRT-18 | Columna de página + salto automático | superseded | Absorbido por VRT-38. |
| VRT-19 | Persistir nombre/descripción de tipo de documento | superseded | Absorbido por VRT-32. |
| VRT-20 | Mejorar columna "Documento" en /audit y /validation | superseded | Absorbido por VRT-38. |
| VRT-21 | Resumen del documento | done | Resumen breve generado por el LLM, antes de la tabla de campos. |
| VRT-22 | Renombrar el proyecto a Veritium | done | Repo, README, API y sidebar pasan a Veritium. |

## F1 — Columna vertebral

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-23 | Capa semántica (núcleo) | done | Entidades, atributos, roles y mapeos campo→atributo; vista consolidada por expediente. |
| VRT-24 | Perfiles de proceso versionados | done | Checklist por tipo o por atributo, reglas vinculadas con su severidad, umbrales; inmutables al publicarse. |
| VRT-25 | Expediente como agregado + API `/v1/cases` | done | `Batch` → `Case`, idempotencia, agregar documentos, corridas con procedencia, contrato de resultado v1. |
| VRT-26 | Ejecución durable sobre aeon | done | `CaseExecutionPort`: grafo por expediente en aeon con pasos en el worker de Veritium; ejecutor interino. |
| VRT-27 | Completitud y veredicto | done | Condiciones de documento o evidencia faltante; veredicto continuar / revisión humana / devolver al cliente. |
| VRT-28 | Outbox + webhooks firmados | done | Eventos transaccionales y entrega Standard Webhooks con reintentos. |
| VRT-29 | Inferencia vía axonium | done | `InferencePort` sobre axonium → prometheus; reemplaza `openai` + `instructor`. |
| VRT-30 | Extracción agéntica sobre synaptum | done | El loop de extracción acotado se porta a `synaptum.Agent`. |
| VRT-31 | Observabilidad con argus | todo | OTLP hacia argus, una traza de punta a punta, costo por expediente. |

## F2 — Diseñador y catálogo

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-32 | Catálogo de tipos documentales en BD | done | Nombre, descripción y esquema por tipo, versionados en la BD en vez de en el código. |
| VRT-33 | Nuevo tipo desde un documento de ejemplo | done | Subir un ejemplo → propuesta de esquema y de mapeo a atributos existentes → revisar y publicar. |
| VRT-34 | UI del catálogo semántico | done | Gestionar entidades, atributos, roles y mapeos desde la web. |
| VRT-35 | Validadores intrínsecos por atributo | done | Formato y validación definidos una sola vez por atributo, no por tipo de documento. |
| VRT-36 | Biblioteca de reglas sobre atributos | done | Lenguaje natural → CEL o procedimiento, con resultado `AMBIGUA` y casos de prueba. |
| VRT-37 | Diseñador de perfiles | done | Armar procesos desde la biblioteca, con sugerencias de reutilización. |

## F3 — Expediente y revisión

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-38 | Vista E2E del expediente | done | Resultado visual, entidades consolidadas y visor de evidencia (página y bbox). |
| VRT-39 | Corrección con motivo y sustento | done | Código de motivo obligatorio + sustento libre en cada corrección. |
| VRT-40 | Reproceso selectivo | done | Reprocesar un atributo, documento, regla o el expediente, según el grafo de dependencias. |
| VRT-41 | Exportes | done | PDF / JSON / YAML / Markdown desde el resultado canónico. |
| VRT-64 | Avance del expediente por etapas | done | Embudo Recibido → Lectura → Clasificación → Extracción → Validación → Decisión, en la lista y en el expediente. |

## F4 — Calidad y comprensión

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-42 | Suites de evaluación | done | Casos desde CSV/Excel y golden sets armados con las correcciones humanas. |
| VRT-43 | Exactitud por campo y calibración | done | Métricas por campo y confianza calibrada que decide automático vs. humano. |
| VRT-44 | Simulación *what-if* y modo sombra | done | Medir un cambio de perfil, regla o modelo contra expedientes históricos antes de publicarlo. |
| VRT-45 | Lentes de Riesgos y Legal | done | Resúmenes y análisis de cláusulas contra un playbook, con evidencia citada. |
| VRT-46 | Prompts versionados y grounding semántico | done | Prompts versionados en synaptum; medir el efecto de inyectar las definiciones semánticas. |
| VRT-63 | Edición gobernada de prompts | done | Un rol técnico edita instrucciones al modelo: borrador, evaluación obligatoria, publicación y vuelta atrás. |

## F5 — Canales

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-47 | Sesión de carga + verificación rápida | done | Carga directa desde el front-end y verificación síncrona en segundos. |
| VRT-48 | *Bulk jobs* | done | Lotes masivos de expedientes de varios procesos, con resultado por expediente. |
| VRT-49 | Eventos CloudEvents | done | Entrada y salida por eventos sobre Kafka o HTTP (claim-check para los archivos). |
| VRT-50 | Salida renderizable (A2UI) | todo | Capa de presentación declarativa sobre el resultado canónico. |
| VRT-65 | Credenciales de sistema y límites por cliente | done | Un sistema se conecta con client credentials propias, revocables, y con cuota de llamadas. |

## F6 — Agéntico

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-51 | Servidor MCP | done | Spec 2026-07-28 + extensión Tasks para operaciones largas. |
| VRT-52 | Servidor A2A | done | A2A v1.0; `input_required` = falta evidencia. |
| VRT-53 | Catálogo de tools | done | Cada tool definida una vez (tipo, costo, rol); de ahí salen las internas y las expuestas por MCP, registradas en aeon. |
| VRT-54 | Asistente del usuario | todo | Asistente sobre synaptum que usa el MCP de Veritium con el token de la persona. |
| VRT-55 | Permisos de tools con Cedar | blocked | Cedar de aeon sobre las tools expuestas y las de terceros (espera `VRT-AEON-006`, aeon `backlog.md:977`). |
| VRT-66 | Agente investigador de discrepancias | done | Ante cada hallazgo, investiga con tools y le deja al revisor diagnóstico, corrección sugerida y evidencia; no decide. |
| VRT-67 | Autovalidación de la extracción | done | El agente de extracción revisa su borrador con las reglas propias del documento y corrige antes de entregar. |
| VRT-68 | Clasificación con escalamiento agéntico | todo | Una llamada para lo claro; un agente que revisa páginas cuando la confianza es baja o el PDF mezcla documentos. |

## F7 — Hardening y producción

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-56 | Ruta de inferencia gobernada | todo | synaptum → aeon-modelgw → prometheus, con presupuestos y costo por corrida. |
| VRT-57 | SSO OIDC y multi-tenant | todo | Identidad corporativa y aislamiento por tenant. |
| VRT-58 | PII y retención | todo | Enmascaramiento según la clase PII semántica; políticas de retención y borrado. |
| VRT-59 | Búsqueda híbrida | todo | BM25 + vectorial en Postgres, con halfvec. |
| VRT-60 | Conectores RENIEC / SUNAT / SBS | todo | Validación contra fuentes oficiales como tools. |
| VRT-61 | Antifraude forense | todo | Detección de documentos alterados o generados con IA. |
| VRT-62 | Auditoría inmutable y cumplimiento | todo | Hash encadenado y requisitos del DS 115-2025-PCM. |
