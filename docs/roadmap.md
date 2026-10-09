# Roadmap — detalle

Una sección por item de [roadmap.md](../roadmap.md). Sin bitácora de cambios: eso vive en los commits.
Hasta v0.3.0 los IDs usaban el prefijo `RM-`; el número es el mismo (`feat(RM-21)` = VRT-21).
Las dependencias con otros equipos se referencian por su ID en el canal compartido (p. ej. `VRT-AEON-001`).

## VRT-01 — Pipeline agéntico de documentos
Done. Commit `b0d98c3`.

## VRT-02 — Segmentación + tipos de documento
Done. Commits `af76c32`, `9797a2f`, `f6f71fb`.

## VRT-03 — Descubrimiento automático de tipos
Done. Commit `ea42c4b`.

## VRT-04 — Módulo web (frontend)
Done. Commits `0bda1ab`, `d4cdc8f`.

## VRT-05 — Vista de auditoría
**Why:** `audit_log` ya se llenaba en cada corrección desde VRT-01; faltaba una ruta que lo expusiera.
**Scope:** solo lectura, sin filtros. Commit `f7d33a3`.

## VRT-06 — Browser de documentos
**Why:** el dashboard solo mostraba unos pocos documentos recientes, sin forma de filtrar el corpus completo.
**Scope:** filtros por estado/tipo/revisión, combinables. Sin búsqueda de texto (eso es VRT-11). Commit `18d5ccd`.

## VRT-07 — Métrica de tiempo ahorrado
**Why:** pedido explícito, con la condición de que el supuesto (min/documento) fuera configurable y visible, no un número inventado.
**Scope:** una tarjeta en el dashboard, cálculo simple sobre documentos completados. Commit `7a6529c`.

## VRT-08 — Roles de usuario
**Why:** hasta este punto cualquier usuario autenticado podía hacer cualquier acción; se necesitaba distinguir quién puede ejecutar vs. solo ver.
**Scope:** tres roles (admin/operador/visor), enforcement en cada endpoint mutante, no solo en la UI. No incluye permisos granulares por recurso. Commit `e265f55`.

## VRT-09 — Pipeline visual en tiempo real
**Why:** `/batches/:id` solo mostraba "procesando" sin detalle de en qué etapa estaba cada documento.
**Scope:** barra de progreso con las etapas reales del pipeline (parsing/clasificando/extrayendo/validando). Commit `4d0f397`.

## VRT-10 — Server-Sent Events
**Why:** el polling de 2s generaba una petición nueva por cliente cada 2s; SSE deja que el servidor empuje solo cuando hay cambio real.
**Scope:** reemplaza el polling en `/batches/:id`. No se extendió a otras vistas. Commit `4734018`.

## VRT-11 — Búsqueda de texto libre
**Why:** los filtros de VRT-06 no cubrían "encontrar un documento por su contenido".
**Scope:** busca nombre de archivo y valores extraídos, combinable con los filtros existentes. Commit `0e126c5`.

## VRT-12 — Editor de sugerencias de tipo
**Why:** antes solo se podía aceptar/rechazar una sugerencia del LLM tal cual — sin forma de corregir un campo mal nombrado sin rechazar toda la propuesta.
**Scope:** edita el borrador (campos, nombre) mientras sigue pendiente. Nunca genera código ni registra el tipo — eso sigue siendo un cambio de código deliberado. Commit `c2675b4`.

## VRT-13 — Vista de auditoría de validación
**Why:** los `validation_issues` ya se persistían por cada regla que no pasaba, sin ninguna vista que los cruzara entre documentos.
**Scope:** lista filtrable por categoría/severidad/tipo. Solo lectura. Commit `988b5aa`.

## VRT-14 — Motor de reglas configurables (CEL)
**Why:** se pidió poder agregar/modificar/desactivar reglas de validación sin depender de un desarrollador. Generar Python real desde la web se descartó por riesgo de seguridad (ejecución de código no revisado); CEL (lenguaje sandboxed de Google, sin efectos secundarios) permite que una regla activada se ejecute de inmediato sin ese riesgo.
**Scope:** cubre categorías `self`/`request_input`/`reference_data` (comparaciones puras de campos). `cross_document` (fuzzy-matching + LLM) y `external_system` (red) siguen siendo código — CEL no puede expresar esa lógica de forma segura. Incluye activar/desactivar cualquier regla, incluidas las hardcodeadas. Commits `ea77e56`, `d5693a6`.

## VRT-15 — UI de Integraciones
**Superseded** por VRT-60 (rediseño enterprise, [ADR-0001](adr/0001-servicio-de-decision-documental.md)).
**Why:** el dashboard de referencia original incluía una sección de integraciones; no se construyó porque no hay ningún sistema externo real conectado detrás.
**Scope:** bloqueado hasta elegir un sistema real (`ExternalSystemPort` en `src/idp/validation/ports.py` es hoy un stub que siempre responde "no verificado"). Requiere: elegir el sistema, construir el adaptador real, y solo entonces la UI tiene algo que mostrar.

## VRT-16 — Corregir layout del visor de documento
**Why:** reportado por el usuario probando `/documents/:id` — react-pdf renderizaba a un ancho fijo en px, y un CSS Grid item no se encoge por debajo del ancho intrínseco de su contenido salvo que se le indique, así que en ventanas angostas el PDF desbordaba su columna.
**Scope:** `PdfViewer` mide su contenedor con `ResizeObserver` y renderiza al ancho real disponible; `min-w-0` en ambas columnas del grid como defensa adicional. Commit `df53ced`.

## VRT-17 — Corregir bounding box resaltado
**Superseded** por VRT-38 (rediseño enterprise, [ADR-0001](adr/0001-servicio-de-decision-documental.md)).
**Why:** reportado por el usuario — al hacer clic en un campo (o varios) para ver dónde se extrajo, el cuadro que se dibuja sobre el PDF aparece desubicado y no coincide con el valor real extraído.
**Scope:** corregir el cálculo de posición del overlay (probablemente un desfase en cómo se escala el bbox normalizado contra el tamaño renderizado de la página).

## VRT-18 — Columna de página + salto automático
**Superseded** por VRT-38 (rediseño enterprise, [ADR-0001](adr/0001-servicio-de-decision-documental.md)).
**Why:** la tabla de campos extraídos no indica en qué página del PDF está cada campo; seleccionar un campo de otra página no mueve el visor hacia ella.
**Scope:** agregar una columna "Página" al inicio de la tabla. Al hacer clic en un campo de otra página, el visor debe navegar a esa página y resaltar el campo — depende de que VRT-17 esté resuelto para que el resaltado sea correcto.

## VRT-19 — Persistir nombre/descripción de tipo de documento
**Superseded** por VRT-32 (rediseño enterprise, [ADR-0001](adr/0001-servicio-de-decision-documental.md)).
**Why:** hoy el catálogo de tipos (`/document-types`, "Plantillas") se arma leyendo constantes de código (`TYPE_DESCRIPTIONS`, `SCHEMA_BY_DOCUMENT_TYPE`); el usuario quiere que el nombre visible y la descripción de cada tipo (ej. `loan_payment_schedule` → "Cronograma de Pagos") vivan en la base de datos, no solo en código.
**Scope:** agregar almacenamiento en BD para nombre/descripción por tipo de documento; mejorar el diseño del listado en `/document-types`. Definir al implementar: tabla nueva de tipos vs. otra estructura, y si el "nombre del documento" que pide VRT-20 sale de aquí.

## VRT-20 — Mejorar columna "Documento" en /audit y /validation
**Superseded** por VRT-38 (rediseño enterprise, [ADR-0001](adr/0001-servicio-de-decision-documental.md)).
**Why:** hoy esas tablas muestran un link genérico o el nombre físico del PDF, sin un nombre legible del documento. Depende de VRT-19 para tener de dónde sacar ese nombre.
**Scope:** mostrar el nombre del documento, con el nombre físico del PDF debajo en texto tenue como subtítulo; el nombre enlaza al detalle del documento. Mismo patrón en ambas páginas — candidato a un componente compartido.

## VRT-21 — Resumen del documento en /documents/:id
**Why:** pedido por el usuario validando VRT-16 — antes de la tabla de campos extraídos quería un resumen breve de qué trata el documento. Se evaluaron dos opciones (descripción genérica del tipo, ya disponible hoy, vs. un resumen real por documento) y el usuario eligió la segunda pese al mayor esfuerzo. `GenericSchema` ya tenía un campo `summary` — solo faltaba replicarlo en los 12 esquemas tipados.
**Scope:** agrega `summary: Extracted[str] | None` a 11 de los 12 esquemas (`email_correspondence` ya tenía `body_summary` con el mismo propósito — no se duplicó); `GenericSchema` ya lo tenía. La extracción agéntica es 100% schema-driven, no hizo falta tocar los extractores. Frontend: extrae `summary`/`body_summary` de la grilla de campos y lo muestra como bloque de texto aparte, arriba de la tabla. Documentos ya extraídos antes de este cambio no tienen resumen (sin backfill). Commit `e4ea81e`.

## VRT-22 — Renombrar el proyecto a Veritium
**Why:** el repo era el único de los proyectos recientes del autor que no seguía su propio patrón de nombres (`<codename clásico>-<dominio>-<tipo>`, como `argus-observability-platform` o `aerarium-agentic-banking`); `agentic-doc-intelligence-platform` era puramente descriptivo y se solapaba con `mercatus-agentic-payments`. *Veritium* (de *veritas*) reclama el diferenciador real: la plataforma no solo extrae campos, los contrasta y deja traza verificable de cada dato.
**Scope:** repo GitHub → `veritium-document-intelligence` (con su remote); branding visible en `README.md`, el `title` de FastAPI, el `<title>` del frontend y el logo del sidebar. Fuera de alcance por diseño: el paquete Python sigue siendo `idp` (renombrarlo tocaría todo el backend sin beneficio visible), y `docker-compose.yml` conserva usuario/BD/volúmenes `idp` — renombrarlos obligaría a recrear los volúmenes y se perdería la base local.

---
# Rediseño enterprise (F1–F7)

Veritium pasa de "subir documentos sueltos" a ser una **capacidad de decisión documental agnóstica al proceso** ([ADR-0001](adr/0001-servicio-de-decision-documental.md)), construida sobre el ecosistema propio sin acoplarse a él ([ADR-0004](adr/0004-capacidades-transversales-sin-acoplamiento.md)).

## F1 — Columna vertebral

## VRT-23 — Capa semántica (núcleo)
**Why:** sin un significado compartido, cada proceso reescribe sus reglas y su validación cruzada por tipo de documento, y los consumidores quedan atados a los esquemas de cada documento ([ADR-0007](adr/0007-capa-semantica-ligera.md)).
**Scope:**
- Catálogo versionado `semantic_catalog_versions` con entidades, atributos (definición, tipo, formato, unidad, cardinalidad, clase PII), roles (titular, cónyuge, asesor…) y mapeos campo→atributo+rol. El seed se deriva de los 12 esquemas actuales.
- Resolución por expediente en una vista consolidada `consistent` / `conflict` / `single_source`, con la evidencia de cada fuente. Regla genérica `semantic.attribute_consistency`.
- La variable CEL `case` expone esa vista. API admin `/v1/semantic-catalog`.
- Fuera de alcance: la UI (VRT-34), los validadores por atributo (VRT-35) y la inyección en los prompts (VRT-46).

## VRT-24 — Perfiles de proceso versionados
**Why:** el mismo motor tiene que servir a "Convenios", "Contratación de tarjetas" o Riesgos con requisitos distintos, y eso se configura como dato, no como código.
**Scope:**
- `process_profiles` y `process_profile_versions`, inmutables al publicarse. Cada versión fija una versión del catálogo semántico.
- Checklist por tipo **o por atributo** (con documentos alternativos), `required_when_cel` y `min_count`.
- `rule_bindings` con `severity`, `blocking` y `on_fail` **en el vínculo, no en la regla**. Umbrales.
- Perfil integrado `ad-hoc` (el comportamiento de v0.3.0) y seed `convenios`. API admin `/v1/profiles`.
- Fuera de alcance: el diseñador web (VRT-37).

## VRT-25 — Expediente como agregado + API `/v1/cases`
**Why:** la unidad de trabajo de un proceso es el expediente de un cliente, que se completa con el tiempo, no un documento suelto ([ADR-0002](adr/0002-strangler-batch-a-case.md)).
**Scope:**
- Migración `batches` → `cases`, con `profile_version_id`, `external_ref`, `idempotency_key`, `channel` y veredicto.
- `case_runs` con la procedencia completa (versiones de código, perfil, catálogo, reglas, modelos, prompts y OCR).
- `POST /v1/cases` (202 + `Idempotency-Key`), `POST /v1/cases/{id}/documents`, `GET /v1/cases/{id}` y `GET /v1/cases/{id}/result` (contrato v1, [ADR-0005](adr/0005-contrato-resultado-outbox-webhooks.md)). Rol `integracion`.
- `/batches` se mantiene como alias con el perfil `ad-hoc`; el frontend no cambia en F1.
- Re-evaluación al agregar documentos: solo se extraen los nuevos y se re-valida todo el expediente; los hallazgos previos quedan `superseded` (no se borran) y un campo ya enviado a revisión no se vuelve a encolar.

## VRT-26 — Ejecución durable sobre aeon
**Why:** hoy un expediente corre en secuencia dentro de `BackgroundTasks`; si el proceso cae, se pierde ([ADR-0003](adr/0003-ejecucion-sobre-aeon.md)).
**Scope:**
- `CaseExecutionPort` (`CASE_EXECUTOR`) con `AeonExecutor`: grafo `start → parallel[process_document × N] → evaluate` de nodos `activity`, con `max_activity_calls = N+2`.
- Worker propio (`python -m idp.worker`) con task queues por carril: `veritium-online`, `veritium-backoffice`, `veritium-bulk`. Actividades idempotentes con estado en la BD de Veritium, heartbeat en `process_document`, y un reconciliador que marca fallida la corrida cuyo run de aeon falló antes de evaluar (aeon no avisa).
- `InProcessExecutor` (default), con paralelismo acotado y **no durable**.
- Instancia **interina** del mismo código de aeon hasta que exista el despliegue compartido multi-tenant (`VRT-AEON-005`); el cambio será solo de configuración: `deploy/aeon/` (override de compose, bundle de Cedar del tenant `veritium` con guarda `ExternalActivity`) y `scripts/aeon_dev.sh` (callers y tokens generados por máquina) ([ADR-0003](adr/0003-ejecucion-sobre-aeon.md)).
- Se cierra cuando A-1 está entregado (`VRT-AEON-001`) y el crash-resume está probado.

## VRT-27 — Completitud y veredicto
**Why:** el proceso que invoca no quiere una lista de campos, sino saber qué hacer después y por qué.
**Scope:**
- `case_conditions` (`missing_document` / `missing_evidence`), que se cierran solas al llegar la evidencia.
- `domain/verdict.py` puro, con precedencia `return_to_client` > `human_review` > `continue` y todos los motivos.
- Solo corren las reglas vinculadas al perfil, con la severidad del vínculo; el umbral de confianza del perfil decide la revisión humana.
- Una condición abierta se puede dispensar con motivo auditado (`POST /v1/cases/{id}/conditions/{cid}/waive`); dispensar o resolver una revisión recalculan el veredicto sin una corrida nueva. Cada corrida guarda su veredicto (historia).

## VRT-28 — Outbox + webhooks firmados
**Why:** el sistema llamador debe enterarse del veredicto sin consultar en bucle, y sin perder ni duplicar notificaciones ([ADR-0005](adr/0005-contrato-resultado-outbox-webhooks.md)).
**Scope:**
- `outbox_events` en la misma transacción que el veredicto.
- `webhook_endpoints` (secreto cifrado) y `webhook_deliveries`.
- Despachador con firma Standard Webhooks, backoff con jitter hasta ~3 días e idempotencia por `webhook-id`. Sink de prueba `scripts/webhook_sink.py`.
- Eventos delgados (ids, estados, veredicto y links; nunca contenido ni datos personales) en sobre CloudEvents 1.0: `pe.veritium.case.run.completed|failed`, `pe.veritium.case.verdict.changed` (solo si el veredicto cambia), `pe.veritium.webhook.test`.
- El despachador corre dentro de la API hasta VRT-26; la carga síncrona de modelos OCR del pipeline puede retrasar entregas unos segundos.

## VRT-29 — Inferencia vía axonium
**Why:** axonium es el SDK obligatorio hacia prometheus, y la ruta de inferencia tiene que poder pasar de autónoma a gobernada sin tocar el dominio ([ADR-0006](adr/0006-inferencia-gobernada-por-fases.md)).
**Scope:**
- `InferencePort` (`llm/port.py`: `structured`, `vision`) sobre `synaptum.generate()` (S-6, journaled) con `LocalGateway` + `AxoniumModel` → gateway de prometheus; imágenes como `Image` (S-7). Sale `instructor`; la validación y la re-pregunta con el error son de synaptum.
- Un cliente de axonium por bucle: lo abren el lifespan de la API y el arranque del worker. Los llamadores siguen síncronos en sus hilos y llegan al puerto por un puente al bucle del puerto (pasarlos a async no cambia el resultado y toca el motor de reglas).
- `Idempotency-Key` de synaptum (run + paso + huella del cuerpo): un reintento tras un crash se sirve como `idempotent_replay`, sin generar otra vez. `finish_reason == "length"` no valida → `NoObjectGeneratedError`.
- Modelos por id del registro de prometheus (`gpt-oss-20b-mxfp4`, `qwen3vl-30b-a3b`); el puerto avisa si respondió otro. Procedencia con versiones de synaptum y axonium.
- Fuera: el loop agéntico sigue llamando directo al servidor de razonamiento hasta VRT-30.

## VRT-30 — Extracción agéntica sobre synaptum
**Why:** los agentes de Veritium se construyen con el framework del ecosistema, no con un loop propio.
**Scope:**
- El loop de `extraction/agentic/` pasa a `synaptum.Agent` (`InferencePort.run_agent`): las tools de lectura son `@tool` async ligadas al documento, el VLM se llama dentro de la tool vía `InferencePort.vision`, y el resultado entra por `submit_tool=True` con `Limits(max_steps=extraction_max_turns)` y `Sampling(temperature=0)`.
- Sin wrappers tolerantes: un argumento mal formado vuelve al modelo como error (S-3). `LimitExceeded` y `NoObjectGeneratedError` pasan a `ExtractionIncomplete` → revisión humana. La re-pregunta consume `max_steps`.
- Sale el último cliente directo (`openai`): todo el tráfico de modelo pasa por synaptum → axonium → prometheus. Los spans de las tools los emitimos nosotros (synaptum los deja a quien ejecuta la tool).

## VRT-31 — Observabilidad con argus
**Why:** con varios procesos, workers y la ruta aeon de por medio, sin una traza de punta a punta no se puede diagnosticar ni atribuir el costo por expediente.
**Scope:**
- OTLP/HTTP al collector de argus con sus atributos de recurso, más el interceptor OTel de `temporalio`.
- Convenciones `gen_ai.provider.name` / `gen_ai.operation.name` y `case_id` en los spans.
- Incorporación vía `VRT-ARG-001`.

## F2 — Diseñador y catálogo
## VRT-32 — Catálogo de tipos documentales en BD
**Why:** hoy los tipos viven en código, así que crear o ajustar un tipo requiere un desarrollador ([ADR-0008](adr/0008-tipos-documentales-como-datos.md)).
**Scope:**
- `document_types` + `document_type_versions` (nombre visible, descripción, pista de extracción, esquema), seed v1 derivado de los esquemas de código con el mismo JSON Schema. API admin `/v1/document-types` (crear, versionar, publicar, retirar); `/document-types` para la web.
- Clasificador, descubrimiento de tipos y extracción leen el catálogo por corrida; un extractor agéntico único reemplaza a los 12 iguales. Cada extracción registra su versión de tipo.
- Publicar rechaza un esquema que quite campos mapeados por el catálogo semántico publicado.
- Fuera: UI de edición (VRT-33/34); las reglas codificadas por tipo siguen igual (VRT-35/36). Absorbe VRT-19.

## VRT-33 — Nuevo tipo desde un documento de ejemplo
**Why:** es el diferenciador frente a las plataformas *schema-first*; evoluciona VRT-03.
**Scope:**
- `POST /v1/document-types/proposals`: un ejemplo (archivo o documento ya cargado) → borrador completo (`DocumentTypeDefinition` + mapeos a atributos del catálogo semántico verificados + aviso si se parece a un tipo existente). No guarda nada.
- `POST /v1/document-types/registrations`: publica el tipo revisado como v1 y sus mapeos como versión nueva del catálogo semántico; valida todo antes de escribir; resuelve la sugerencia de origen (`registered`).
- Página "Nuevo tipo desde un ejemplo" (admin): revisar y editar campos, textos y mapeos. Desde Plantillas, y desde cada sugerencia aceptada con su documento.
- Fuera: editar una versión nueva de un tipo existente desde la web (VRT-34).

## VRT-34 — UI del catálogo semántico
**Why:** la capa semántica la mantienen usuarios de negocio, no desarrolladores.
**Scope:**
- Página `/semantic-catalog`: mapeos, atributos, entidades y roles; edición (admin) → borrador → publicar; versiones con los perfiles que fijan cada una.
- Un borrador se rechaza si un mapeo apunta a un tipo no publicado o a un campo que su esquema vigente no tiene.
- Fuera: adoptar una versión nueva del catálogo en un perfil sigue siendo una versión nueva del perfil por API (VRT-37).

## VRT-35 — Validadores intrínsecos por atributo
**Why:** el formato de un DNI no depende del documento en el que aparece.
**Scope:**
- `semantic.format.<atributo>`: una regla por atributo con `format_cel`, construida desde la versión del catálogo que usa la corrida; valida todo valor que cualquier documento aporte a ese atributo. Hoy `persona.dni` y `empleador.ruc`.
- Retira las 9 `DniFormatValid` por tipo. Los perfiles publicados que las vinculan siguen funcionando: sus ids se resuelven a la regla nueva con la vinculación más estricta; una versión nueva de perfil debe usar el id nuevo.
- El formato se edita en la página del catálogo semántico (columna `format_cel`).

## VRT-36 — Biblioteca de reglas sobre atributos
**Why:** las reglas en lenguaje humano tienen que poder usar tools y no solo comparar campos, sin abrir la puerta a código arbitrario.
**Scope:**
- Una regla CEL es sobre los campos de un tipo de documento o sobre un atributo semántico (`value`, en cualquier documento que lo aporte), con `case` y `request` disponibles.
- Lenguaje natural → CEL con resultado `AMBIGUA` explícito: si falta un umbral o una definición, la IA devuelve las preguntas y no guarda nada.
- Casos de prueba por regla (propuestos por la IA, editables); activar exige que todos den lo esperado. Aprobación humana como antes.
- Fuera: el procedimiento acotado con tools (RENIEC/SUNAT/SBS) espera a que existan esos conectores (VRT-60); diseñarlo antes sería especulativo.

## VRT-37 — Diseñador de perfiles
**Why:** configurar un proceso nuevo debe ser reutilizar, no partir de cero.
**Scope:**
- Páginas `/profiles` y editor: catálogo semántico fijado (con aviso si hay uno más nuevo), requisitos por tipo o por evidencia (con qué tipos la satisfacen), reglas vinculadas con severidad/bloqueo, borrador → publicar.
- `GET /v1/profiles/library`: tipos, atributos, roles y reglas vinculables de una versión del catálogo, con dónde corren y qué perfiles ya los usan; las sugerencias son reglas que corren sobre los documentos del perfil o que usan otros procesos.
- Una versión nueva parte de la activa con los ids retirados (VRT-35) ya convertidos.

## F3 — Expediente y revisión
## VRT-38 — Vista E2E del expediente
**Why:** el ejecutivo necesita ver el resultado completo y su evidencia en un solo lugar. Absorbe VRT-17, VRT-18 y VRT-20.
**Scope:**
- Páginas `/cases` y `/cases/:id`: veredicto con motivos (agrupados), requisitos con dispensa, entidades consolidadas con sus fuentes, hallazgos y documentos con su nombre visible; cada fuente abre el visor en su página con su recuadro.
- `EvidenceViewer`: PDF o imagen (PNG/JPG) con la misma superposición; también en el detalle de documento y las miniaturas.
- Recuadros fieles: el OCR ya no endereza ni rota la página (medido: desplazaba ~20 px los recuadros respecto de la imagen original).

## VRT-39 — Corrección con motivo y sustento
**Why:** sin un motivo codificado no se puede medir por qué se corrige.
**Scope:**
- Siete motivos codificados (`domain/correction_reasons.py`: error de OCR, otro dato, no extraído, formato, ilegible, decisión de negocio, valor correcto); obligatorio en `POST /review/{id}`, con sustento obligatorio para ilegible y decisión de negocio.
- Ambos en el `audit_log`; `GET /audit/correction-summary` cuenta por motivo y tipo de documento; la cola de revisión y la auditoría los muestran.
- La cola nombra cada campo por su atributo semántico y rol (o el campo del tipo / la clave genérica), con documento, página, texto fuente y el hallazgo que lo envió (`review/labels.py`).

## VRT-40 — Reproceso selectivo
**Why:** corregir un campo no debe obligar a reprocesar todo el expediente, y hasta aquí una corrección ni siquiera llegaba al dato que leen las reglas.
**Scope:**
- `POST /v1/cases/{id}/reprocess` con alcance `case` | `document` (re-extraen y re-evalúan todo) o `rule` | `attribute` (re-evalúan solo las reglas alcanzadas; los hallazgos de las demás siguen vigentes). Cada uno es una corrida nueva con su `scope` en `case_runs`.
- Grafo campo → regla: cada regla declara qué lee (`ValidationRule.reads`: campos y `@atributo`); las CEL lo derivan de su expresión; lo desconocido se re-evalúa siempre.
- Una corrección se escribe en la extracción (confianza 1.0, misma evidencia) y dispara una corrida `correction` sobre ese campo. Re-extraer re-aplica las correcciones; si la re-extracción falla, la extracción anterior se conserva y la corrida lo dice.
- Fuera: re-extraer documentos segmentados (409) y guardar el historial de extracciones por corrida.
## VRT-41 — Exportes
**Why:** el resultado se comparte fuera de la plataforma.
**Scope:**
- `GET /v1/cases/{id}/result` por `Accept` o `?format=` (descarga): JSON y YAML son el contrato v1 tal cual; Markdown y PDF, un informe derivado de él (`export/case_result.py`) con los nombres de los catálogos, no las claves.
- La vista del expediente tiene un menú «Exportar».
- Fuera: plantillas de informe por cliente o marca, y firma del PDF.

## F4 — Calidad y comprensión
## VRT-42 — Suites de evaluación
**Why:** sin evaluación no se puede cambiar un modelo, prompt o tipo documental con seguridad.
**Scope:**
- Suite = documentos con su tipo y valores esperados, desde una tabla CSV/Excel (`archivo`, `tipo`, `paginas`, un campo por columna; plantilla por tipo) o como golden set desde las correcciones (sin las decisiones de negocio).
- Una corrida clasifica y extrae con la configuración del momento, sin crear expedientes, y guarda métricas (clasificación, campos, por campo) y procedencia; se compara con la corrida anterior (regresiones y mejoras). UI en `/evaluation`.
- Fuera: evaluar reglas y veredictos (VRT-44), calibración (VRT-43), campos lista, curar casos desde la UI y correr sobre aeon (corre en la API, reanudable).
## VRT-43 — Exactitud por campo y calibración
**Why:** una confianza mal calibrada deja pasar errores con confianza alta; medido en VRT-42, el modelo dice 100% y acierta 50–67% en algunos campos.
**Scope:**
- Observaciones etiquetadas: la última corrida de cada suite de evaluación y las revisiones que ninguna suite cubre (sin decisiones de negocio).
- Por campo: acierto, confianza media, ECE, Brier y confianza calibrada por tramos (suavizada hacia el acierto del campo, no decreciente); umbrales sugeridos para 1/2/5% de error con su cobertura.
- Versiones inmutables; un admin activa una y la cola de revisión compara la confianza calibrada con el umbral del perfil; la corrida registra la versión. UI en `/calibration`.
- Fuera: recalcular solo y fijar el umbral del perfil automáticamente (lo decide una persona).
## VRT-44 — Simulación *what-if* y modo sombra
**Why:** medir el impacto de un cambio de proceso antes de publicarlo, sin tocar expedientes.
**Scope:**
- Candidato = una versión de perfil (checklist, reglas vinculadas incluidas las en borrador, catálogo y umbrales). Sobre el historial: re-decide los últimos N expedientes del proceso con lo ya extraído; en sombra: decide cada expediente nuevo también con el candidato, sin afectar el veredicto ni los webhooks.
- Resultado en lenguaje de negocio: cuántos cambiarían, de qué decisión a cuál, y los motivos que aparecen o desaparecen (comparados por lo que tratan, no por su texto). UI en `/simulations`, con acceso desde el borrador en Perfiles.
- Fuera: simular cambios de modelo o prompt (eso es VRT-42) y re-extraer en la simulación.
## VRT-45 — Lentes de Riesgos y Legal
**Why:** las áreas aguas abajo necesitan comprender documentos, no solo validarlos.
**Scope:**
- Lentes como datos editables (`/lenses`): resumen con foco (Riesgos) o playbook de puntos con importancia (Legal), y los tipos de documento que leen. Semilla: resumen crediticio, carta de autorización de descuento, compra de deuda.
- Leer un expediente con una lente: el modelo recibe primero los datos ya extraídos y conciliados ([fN]) y luego el texto OCR numerado ([dN:R]); cada afirmación cita referencias que se resuelven a página y recuadro. Citas inexistentes se descartan y una cita textual que no está en el documento se marca para verificar.
- El texto OCR de cada archivo se guarda junto a él al procesarlo (los anteriores se leen una vez más la primera vez).
- Fuera: lentes que corren solas en cada corrida y versionado de lentes (cada lectura guarda la definición que usó y se marca si la lente cambió).
## VRT-46 — Prompts versionados y grounding semántico
**Why:** reproducibilidad y calidad de extracción medible. **Scope:** prompts versionados (synaptum, S-8) y la medición de inyectar definiciones semánticas.

## F5 — Canales
## VRT-47 — Sesión de carga + verificación rápida
**Why:** el canal en línea no puede esperar el pipeline completo. **Scope:** token efímero / URL prefirmada y verificación síncrona en segundos (calidad, tipo, legibilidad).
## VRT-48 — *Bulk jobs*
**Why:** el backoffice procesa en masa sin afectar al canal en línea. **Scope:** lotes multi-expediente en el carril `bulk`, con resultado por expediente.
## VRT-49 — Eventos CloudEvents
**Why:** integración por eventos con sistemas que ya hablan por bus. **Scope:** consumidor y publicador CloudEvents, con claim-check para los archivos.
## VRT-50 — Salida renderizable (A2UI)
**Why:** que otros front-ends muestren el resultado sin conocer el dominio. **Scope:** capa A2UI v0.9 sobre el contrato canónico.

## F6 — Agéntico
## VRT-51 — Servidor MCP
**Why:** otros agentes deben poder usar Veritium como tool. **Scope:** spec 2026-07-28 + Tasks; tools y recursos sobre el mismo núcleo.
## VRT-52 — Servidor A2A
**Why:** delegación entre agentes con un ciclo de vida estándar. **Scope:** A2A v1.0, con Agent Card firmada e `input_required` = falta evidencia.
## VRT-53 — Catálogo de tools
**Why:** las validaciones y los agentes necesitan herramientas tipadas y gobernadas. **Scope:** registro de tools deterministas o probabilísticas, con permisos y costo.
## VRT-54 — Asistente del usuario
**Why:** ayudar a operar, buscar y diagnosticar sin conocer la plataforma por dentro. **Scope:** agente synaptum que consume las mismas tools MCP.
## VRT-55 — Permisos de tools con Cedar
**Why:** gobernar qué agente usa qué tool. **Scope:** políticas Cedar de aeon sobre el catálogo de tools.

## F7 — Hardening y producción
## VRT-56 — Ruta de inferencia gobernada
**Why:** en producción todo el tráfico de modelo debe tener presupuestos, atribución y gobierno ([ADR-0006](adr/0006-inferencia-gobernada-por-fases.md)). **Scope:** adaptador gobernado del `InferencePort` y del `AgentRuntime`. `VRT-AEON-003` (A-2/A-3) entregada el 2026-10-08; falta S-4/S-5 (`VRT-SYN-003`) y, para un despliegue compartido, el tenant del run en la política y el techo (`VRT-AEON-005`).
## VRT-57 — SSO OIDC y multi-tenant
**Why:** identidad corporativa y varias unidades de negocio. **Scope:** OIDC y aislamiento de datos y configuración por tenant.
## VRT-58 — PII y retención
**Why:** Ley 29733 y datos sensibles hacia el LLM. **Scope:** enmascaramiento derivado de la clase PII semántica; retención y borrado.
## VRT-59 — Búsqueda híbrida
**Why:** el `ILIKE` de VRT-11 no escala. **Scope:** BM25 + vectorial en Postgres con halfvec, filtrado por tenant y proceso.
## VRT-60 — Conectores RENIEC / SUNAT / SBS
**Why:** validar contra fuentes oficiales; desbloquea lo que VRT-15 no pudo. **Scope:** conectores como tools del catálogo. Absorbe VRT-15.
## VRT-61 — Antifraude forense
**Why:** los documentos financieros falsificados con IA crecieron ~4x (2025–2026); validar la coherencia no los detecta. **Scope:** forense del archivo (metadatos, fuentes, píxeles, estructura).
## VRT-62 — Auditoría inmutable y cumplimiento
**Why:** el DS 115-2025-PCM clasifica la evaluación crediticia como de alto riesgo. **Scope:** auditoría con hash encadenado y requisitos de transparencia (confirmar el alcance con Legal).
