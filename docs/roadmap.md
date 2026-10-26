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
- `argus.init()` como `veritium-api` y `veritium-worker` (namespace `veritium`), con el middleware ASGI, el interceptor OTel de Temporal y las auto-instrumentaciones (FastAPI, httpx, SQLAlchemy). Apagado con `ARGUS_DISABLED=1`, que la suite fija sola.
- Un span por paso del expediente con `idp.case_id`, `idp.run_id` e `idp.document_id`; un span GenAI por llamada al modelo con `gen_ai.provider.name` y `gen_ai.operation.name`, modelo y tokens. El contexto cruza al loop del puerto de inferencia.
- Verificado el 2026-10-13: un reproceso es una sola traza, de la API a aeon, Temporal y el worker, con el costo por expediente consultable (la consulta, en `observability/otel.py`).
- Fuera: pasos propios de nivel 2 más allá de los del expediente, y el paso a `activo`, que hace argus al verificar.

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

## VRT-64 — Avance del expediente por etapas
**Why:** mientras un expediente se procesa no se veía en qué etapa iba; «processing» no le dice nada a un operario.
**Scope:**
- `progress` en la lista y el resumen de cada expediente (`domain/case_progress.py`): seis etapas (Recibido, Lectura, Clasificación, Extracción de datos, Validación, Decisión), cada una hecha / en curso / pendiente / con error, con cuántos documentos van, derivado del estado de cada documento y de la última corrida.
- Embudo compacto en Expedientes (se refresca cada 3 s mientras hay expedientes en proceso) y completo en el expediente; estados en español.
- Fuera: tiempos por etapa y avance dentro de una etapa (p. ej. página por página).

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
**Why:** reproducibilidad y calidad de extracción medible.
**Scope:**
- Registro de prompts (`llm/prompts.py`): cada uno con nombre y versión = huella de su texto; se pasa a synaptum como `PromptTemplate`, que lo sella en el diario y la traza (S-8). La procedencia de corridas de expediente y de evaluación guarda la versión de cada prompt.
- Grounding semántico: el prompt de extracción puede incluir el significado de negocio de cada campo (catálogo semántico). Apagado por defecto (`EXTRACTION_SEMANTIC_GROUNDING`); se mide por corrida de evaluación y la comparación dice qué cambió entre corridas.
- Medido con el golden set de boletas: sin diferencia (60% de campos en ambos); hace falta una suite más grande para decidir.
- Pantalla de solo lectura «Instrucciones al modelo» (`/prompts`): para qué sirve cada una, versión en uso y desde cuándo, texto, versiones anteriores (guardadas al arrancar, tabla `prompt_versions`) y, desde un expediente o una evaluación, con qué versión se hizo.

## VRT-63 — Edición gobernada de prompts
**Why:** un perfil técnico debe poder mejorar las instrucciones sin desplegar código, y un cambio de prompt afecta a todos los expedientes desde ese momento.
**Scope:**
- Rol «Especialista IA» (aparte de admin): edita instrucciones y crea y corre evaluaciones; el resto solo consulta (`/prompts`).
- Borrador con motivo que debe conservar los datos que la plataforma completa (cada prompt los declara al registrarse); diferencias línea por línea con el texto en uso.
- Una evaluación puede probar borradores solo para esa corrida; publicar exige una evaluación terminada con el borrador, o una confirmación explícita para instrucciones que ninguna evaluación ejercita. Vuelta a cualquier versión anterior o al texto del código en un clic.
- Texto en vigor: borrador en prueba > publicado (BD, tabla `prompt_edits` con la auditoría) > código; la API lo aplica al publicar y el worker en el siguiente ciclo (~30 s). La versión sigue siendo la huella del texto efectivo.
- Fuera: simular con expedientes pasados un cambio de prompt que influye en el veredicto, y aprobación por una segunda persona.

## VRT-69 — Agente de extracción eficiente
Método, mediciones y aprendizajes: [eficiencia-modelos-ia.md](eficiencia-modelos-ia.md).
**Why:** la extracción es el 70–90% del tiempo de cada documento. Medido el 2026-10-10 (4 documentos reales, tokens por turno): el costo es lo que el modelo **escribe**, no lo que se le envía (entrada ≤13k tokens con ~95% servido de caché). La mayor pérdida son turnos en que gpt-oss, a temperatura 0, entra en un bucle de razonamiento hasta el tope de 8.192 tokens (3 de 6 turnos en una solicitud de préstamo: 17 min). **Scope:**
- Hecho: un turno cortado al tope se repite una vez con temperatura 0.6; el agente escribe solo valor, confianza, texto y región (página y caja las pone la plataforma); la lista de regiones omite las vacías y marca con «…» las recortadas; las listas se entregan completas.
- Descartado con medición: razonamiento «low» (−86% de tiempo, exactitud 83% → 74%) y temperatura 1.0 en todo (sin bucles, pero 69%).
- Medido el 2026-10-13, 3 corridas por variante sobre 4 documentos con valores verificados a mano: exactitud 65% → 84%, tiempo medio 1.073 s → 665 s (peor caso 2.079 s → 745 s), salida 62,7k → 30,1k tokens. Siguiente, fuera de este ítem: cortar el bucle apenas empieza (streaming) en vez de esperar al tope; cada bucle aún cuesta ~80 s.

## VRT-70 — Lectura (OCR) más rápida en el mismo hardware
Método, mediciones y aprendizajes: [eficiencia-modelos-ia.md](eficiencia-modelos-ia.md).
**Why:** la lectura era la segunda etapa más cara (13,9 s por página A4 en CPU) y prometheus mostró que estábamos en el runtime más lento para Mac (`PRM-VRT-002`). **Scope:**
- Medido el 2026-10-13 sobre 9 páginas reales: los mismos modelos de Paddle sobre ONNX Runtime leen en 1,1 s por página (≈2 s con layout), con 470 de 507 líneas idénticas y cajas a 1 px; la exactitud de la extracción se mantiene (82% frente a 84%, dentro de la variación entre corridas). Es el lector por defecto (`rapidocr`).
- Condición medida: nuestra conversión de los modelos (`scripts/export_ocr_onnx.sh`) y los parámetros de detección de Paddle. Los archivos y valores por defecto de RapidOCR leen peor y bajaron la extracción a 69–71%.
- Descartado: detector `mobile` (pierde valores), CoreML (más lento), cambiar hilos, lotes u orientación de línea en Paddle (sin ganancia). Fuera: el layout sigue en Paddle (0,6 s por página, ~5 GB de pico).

## F5 — Canales

## VRT-47 — Sesión de carga + verificación rápida
**Why:** el canal en línea no puede esperar el pipeline completo: quien sube una foto mala debe saberlo mientras aún puede repetirla.
**Scope:**
- `POST /v1/upload-sessions` (sistema que llama u operador, «Enlace de carga» en Expedientes) abre una sesión con token efímero (solo su hash en BD) y entrega el enlace `/carga/{id}#t=…`; página pública, sin cuenta, para el teléfono.
- Cada archivo se revisa en 1–3 s: se abre (dañado, contraseña, formato), nitidez, luz, página en blanco y resolución con umbrales medidos en documentos reales; tipo con el modelo de visión y las descripciones del catálogo, con tiempo límite. Solo lo ilegible se rechaza; lo demás advierte, en palabras del cliente.
- Los requisitos del perfil se muestran ya filtrados por los datos del proceso, con los tipos que cumplen cada uno (también por atributo); enviar crea el expediente (o completa uno existente) en el canal `online`, sin los archivos rechazados, una sola vez.
- Fuera: URL prefirmada directa al almacenamiento (la verificación necesita pasar por la API) y QR del enlace.

## VRT-48 — *Bulk jobs*
**Why:** el backoffice procesa en masa sin afectar al canal en línea. **Scope:**
- ZIP con una carpeta por expediente (su nombre es la referencia) y manifiesto opcional (perfil y datos del proceso por expediente); lo inutilizable se omite con su motivo.
- Carril `bulk`: las corridas esperan `queued` y se liberan de a pocas (`bulk_max_in_flight`), sea cual sea el ejecutor.
- Avance y resultado por expediente (pantalla y CSV) y evento `bulk_job.completed`. Fuera: carga por URL o almacenamiento externo (VRT-49).

## VRT-49 — Eventos CloudEvents
**Why:** integración por eventos con sistemas que ya hablan por bus. **Scope:**
- Bus con protocolo Kafka (Redpanda en local, `EVENT_BUS_BROKERS`): el outbox se publica completo (CloudEvents estructurado, clave = expediente, `acks=all`, productor idempotente).
- Comandos `case.submit` y `case.documents.add` por el bus o por `POST /v1/events` (modos estructurado y binario), respondidos con `command.accepted` / `.rejected`; un comando repetido (mismo `source` + `id`) recibe la misma respuesta sin repetir nada.
- Claim-check: los documentos llegan por referencia `s3://` o `https://`, solo desde prefijos permitidos (anti-SSRF). Fuera: esquemas registrados (schema registry) y otros buses nativos.

## VRT-50 — Salida renderizable (A2UI)
**Why:** que otros front-ends muestren el resultado sin conocer el dominio. **Scope:** capa A2UI v0.9 sobre el contrato canónico.

## VRT-65 — Credenciales de sistema
**Why:** hoy un sistema solo entra como una persona (usuario y contraseña, token de 8 h); para integrarse de verdad necesita credenciales propias que se roten y revoquen sin tocar a nadie más. **Scope:**
- Alta de sistemas por un admin: `client_id` + secreto mostrado una sola vez; rotar y revocar con efecto inmediato.
- `POST /auth/token` (OAuth2 client credentials) → token corto con rol `integracion`.
- Cuota de llamadas por minuto y por sistema (429 + `Retry-After`); arranque rechazado fuera de dev con la clave JWT por defecto. Fuera: SSO de personas y multi-tenant (VRT-57).

## F6 — Agéntico

## VRT-51 — Servidor MCP
**Why:** otros agentes deben poder usar Veritium como tool. **Scope:**
- `/mcp` (Streamable HTTP, spec 2026-07-28, sin estado; clientes 2025-11-25 también): tools `list_processes`, `submit_case`, `add_documents`, `get_case_status`, `get_case_result`, `find_cases` y el recurso `veritium://cases/{id}/result`.
- Extensión Tasks: crear o completar un expediente devuelve una tarea cuyo id es la corrida persistida (`tasks/get` sirve desde cualquier instancia).
- Mismas identidades, roles y cuota que la API (login o credenciales de sistema de VRT-65; metadata RFC 9728/8414). Fuera: MRTR/elicitación y `notifications/tasks` (las tareas se consultan por sondeo).

## VRT-52 — Servidor A2A
**Why:** delegación entre agentes con un ciclo de vida estándar. **Scope:**
- A2A v1.0 con el SDK oficial: JSON-RPC en `/a2a/` y HTTP+JSON en `/a2a/rest`; Agent Card en `/.well-known/agent-card.json`, firmada (JWS ES256 sobre RFC 8785) con la clave pública en `/.well-known/jwks.json`.
- Una tarea es un expediente: el primer mensaje lo abre (parte de datos + documentos por url autorizada o contenido) y la tarea sigue su corrida; `input-required` = faltan documentos, que se envían en la misma tarea; el veredicto llega en el artefacto `resultado`.
- Tareas en Postgres por dueño (mismas identidades, roles y cuota que la API); una tarea que un reinicio dejó en curso se resuelve desde su corrida al leerla. Fuera: notificaciones push (hay webhooks) y compatibilidad A2A 0.3.

## VRT-53 — Catálogo de tools
**Why:** las validaciones y los agentes necesitan herramientas tipadas y gobernadas, sin definirlas dos veces. **Scope:**
- Cada tool se define una sola vez (determinista o con modelo, costo, rol que la usa); de esa definición salen las tools internas (synaptum `@tool`) y las expuestas por MCP.
- Criterio de exposición: MCP solo donde se cruza una frontera de proceso, dueño o confianza; los pasos internos (clasificar, extraer, leer regiones) no se exponen. Próximas a exponer: enlace de carga, verificación rápida, evidencia de un dato, lentes.
- Catálogo consultable (`GET /v1/tools`, pantalla «Catálogo de tools») y descriptores MCP con sus metadatos (`GET /v1/tools/mcp`) para federarlas; registrarlas en el catálogo de aeon espera `VRT-AEON-006`. Las tools de terceros (RENIEC/SUNAT/SBS, VRT-60) se consumirán por MCP desde el gateway de tools de aeon.

## VRT-54 — Asistente del usuario
**Why:** ayudar a operar, buscar y diagnosticar sin conocer la plataforma por dentro. **Scope:** agente synaptum que consume el MCP de Veritium (`MCPTools`) con el token de la persona: mismos permisos, cuota y auditoría que ella, sin un segundo camino con privilegios. Solo usa las tools de lectura; las que cambian algo (abrir expediente, pedir documentos, lentes) quedan como botones en la UI. Para servirle se sumaron al MCP la búsqueda por día, veredicto, estado y proceso, `cases_overview` y `get_review_queue`; los números los calcula Veritium (`summary`), no el modelo. La conversación vive en el cliente.

## VRT-55 — Permisos de tools con Cedar
**Why:** gobernar qué agente usa qué tool donde hay frontera. **Scope:**
- Las tools MCP de Veritium están federadas en aeon (`deploy/aeon/tool_sources.yaml`, aeon `TOOL-010`). Cada tool está aprobada y clasificada una por una, con su descriptor fijado por huella. Las escrituras llevan clave de idempotencia. `request_documents_link` queda fuera.
- Cedar (`deploy/aeon/policies/veritium.yaml`): lecturas abiertas al agente asistente y a los clientes MCP; escrituras sin permiso (denegadas) hasta que un agente real las necesite.
- Verificado con `scripts/aeon_dev.sh verify-tools`: por las dos puertas de aeon, una lectura permitida llega y una escritura denegada nunca llega (el expediente no existe en Veritium); la bitácora de aeon registra ambas.
- Límites de aeon: la puerta MCP tiene un solo principal para todo cliente, y el control por agente solo existe en `POST /execute`. Lo que cada cliente ve lo acota Veritium: su token es de una unidad de negocio (VRT-57).
- Fuera: las tools internas del agente de extracción (en proceso, sobre un documento propio).

## VRT-66 — Agente investigador de discrepancias
**Why:** un 32 % de los documentos termina con campos para revisión humana, casi todos por hallazgos de validación (maestro de empleados y consistencia entre documentos); el revisor empieza cada uno desde cero. **Scope:**
- Agente synaptum con 6 tools internas del catálogo (evidencia de un dato, leer y buscar en un documento, mirar una región con visión, comparar nombres, maestro de empleados); deja diagnóstico, causa, acción sugerida y evidencia verificada contra el texto. No decide ni corrige: la sugerencia se aplica desde la cola de revisión.
- A demanda (por hallazgo o por expediente) para controlar el costo de modelo. Métrica: % de sugerencias aceptadas, registrado solo al corregir el campo (`GET /v1/investigations/stats`).

## VRT-67 — Autovalidación de la extracción
**Why:** muchos hallazgos (formato, aritmética interna) los puede detectar el propio agente antes de entregar, si tiene con qué. **Scope:**
- Tool interna `check_draft`: corre sobre el borrador las reglas propias del documento (categoría SELF: aritmética interna, formato de cada atributo del catálogo semántico, reglas CEL propias); el agente corrige o, si el documento dice eso, entrega igual.
- Medible: opción de las corridas de evaluación para comparar con y sin autovalidación sobre el mismo golden set. Fuera: reglas entre documentos (eso es VRT-66).
- Apagada por defecto: medido el 2026-10-10, solo 2 de 74 documentos con hallazgos tenían uno que pudiera detectar (el resto: maestro de empleados y consistencia entre documentos), y cada revisión es un turno más del modelo.

## VRT-68 — Clasificación con escalamiento agéntico
**Why:** la clasificación es una sola llamada; los casos dudosos o los PDF mezclados quedan "genéricos" o mal clasificados. **Scope:** se mantiene la llamada única para los casos claros; con confianza baja o mezcla, un agente revisa páginas (texto, imagen, descripciones de los tipos). Métrica: % de genéricos y de mal clasificados en las suites.
- **Medido el 2026-10-10, sin construir:** de 188 documentos, 16 quedaron "genéricos", pero fue porque se clasificaron antes de existir su tipo. Reclasificados hoy con una sola llamada, 10 de 10 salen bien (el único genérico real sigue genérico). La confianza no sirve de señal de escalamiento: siempre ≥ 0,8. Se reabre si las suites muestran errores de clasificación.

## F7 — Hardening y producción

## VRT-56 — Ruta de inferencia gobernada
**Why:** en producción todo el tráfico de modelo debe tener presupuestos, atribución y gobierno ([ADR-0006](adr/0006-inferencia-gobernada-por-fases.md)). **Scope:**
- `INFERENCE_ROUTE=governed`: el `InferencePort` usa el `HttpModel` de synaptum contra aeon-modelgw con el token de Veritium. Pide **perfiles** (`deploy/aeon/model_policy.yaml`: razonamiento y visión, locales y `restricted`) y aeon resuelve el modelo con su credencial de prometheus. Obligatoria en producción.
- Cada llamada va atribuida: la de un paso de expediente, a su run de aeon y al agente `veritium-case-run`; la demás (asistente, lentes, investigaciones, borradores), a un run propio y al agente `veritium-service`. Los presupuestos (llamadas, tokens, USD) están en los manifiestos (`deploy/aeon/agents/`); al agotarse, aeon responde 402 y Veritium lo dice así. El costo queda por run en el ledger de aeon.
- Fuera: el diario compartido de synaptum (S-5), porque aeon ignora `sub_run_id` al leerlo (reportado); la durabilidad la siguen dando la actividad y la idempotencia de prometheus. Y el resto de S-4 (`/decide`, `/execute`).
- Bloqueada (`VRT-AEON-008`): `/v1/chat/completions` responde 502 a un turno con argumentos de tool rotos (el bucle de `VRT-69`) en vez de pasarlo, así que la extracción falla por la ruta gobernada. Desarrollo vuelve a la autónoma hasta que aeon lo arregle.

## VRT-71 — Administración de plataforma y unidad en blanco
**Why:** para entregar una unidad a una persona real del banco: que configure su proceso desde cero sin poder cambiar lo que usan las demás unidades. **Scope:**
- Rol de plataforma (`veritium:plataforma:admin` o `:especialista_ia` en el proveedor, o por script): solo ese rol cambia tipos de documento, catálogo semántico, biblioteca de reglas, lentes, instrucciones al modelo y las unidades. El admin de una unidad configura lo suyo: procesos, personas, sistemas, conservación.
- Una unidad nueva nace en blanco (solo el proceso interno ad-hoc); los procesos de ejemplo, si se piden. `plataforma` es un identificador reservado.
- «Primeros pasos»: el orden para dejar lista una unidad, quién hace cada paso y el enlace; el inicio de una unidad vacía lleva ahí.

## VRT-72 — Borrado físico y lógico
**Why:** no había cómo borrar nada, y lo subido por error o de prueba ocupaba espacio para siempre (los archivos son lo que más pesa). **Scope:**
- Físico, con archivos: expediente (solo admin, con motivo en el registro de accesos), documento suelto (el expediente se reevalúa), carga masiva con sus expedientes, suite de evaluación, prueba, sugerencia de tipo, borradores (proceso, tipo, catálogo, regla, calibración), archivo quitado de una sesión de carga. Un archivo se borra solo cuando ninguna fila lo usa.
- Lógico cuando la historia lo nombra: proceso, tipo documental o lente ya usados se archivan; una regla que ya se aplicó se desactiva. Una persona se quita de la unidad; una unidad solo se borra sin expedientes.
- Limpieza automática a 30 días (`technical_retention_days`): eventos y entregas de webhook, tareas A2A terminadas y sesiones de carga cerradas.
- Fuera: auditoría y registros de acceso y validación, que nunca se borran. Al borrar un expediente se va su historial de correcciones; queda la constancia de quién lo borró.

## VRT-57 — SSO OIDC y multi-tenant
**Why:** identidad corporativa y varias unidades de negocio que no deben ver lo de las otras. **Scope:**
- Tenant = unidad de negocio de una misma empresa. Son de cada unidad: expedientes y todo lo que cuelga de ellos, procesos, sistemas conectados, webhooks, maestros, evaluación, calibración, simulaciones y cargas. Son corporativos: catálogos de tipos y semántico, biblioteca de reglas, lentes, instrucciones al modelo y las personas.
- Aislamiento en una sola costura (`persistence/tenancy.py`): toda consulta filtrada, toda fila sellada, fallo cerrado sin unidad; otra unidad responde 404, nunca 403. La unidad viene de la credencial, nunca de la petición; el worker, la carga masiva, los webhooks y el bus declaran la suya.
- Una persona trabaja en varias unidades con un rol en cada una; un token por unidad (`/auth/switch`). SSO OpenID Connect (código + PKCE) con cualquier proveedor; unidad y rol desde los grupos `veritium:<unidad>:<rol>`; las unidades las registra el operador. Keycloak para desarrollo.
- Fuera: RLS en Postgres (el comportamiento está fijado por pruebas negativas por tabla), un proveedor de identidad por unidad, y quién edita el catálogo corporativo (hoy los admin y especialistas de cualquier unidad).

## VRT-58 — PII y retención
**Why:** Ley 29733: un dato personal se muestra solo a quien lo necesita, queda constancia de quién lo vio, y se borra cuando ya no hace falta o el titular lo pide. **Scope:**
- Enmascarado por defecto en pantalla, API, MCP, A2A y CSV, derivado de la clase PII del catálogo semántico (sensible oculto; personal con últimos dígitos o iniciales; un campo sin mapeo cuenta como personal). El enmascarador conoce los valores del expediente y los tapa también donde se citan (hallazgos, motivos, evidencia, errores).
- «Ver datos»: operador, admin y sistemas conectados (una ventana de 15 min por clic, o `?reveal=true` por llamada); visor y especialista IA nunca. El original y la búsqueda por un dato, igual. Todo queda en `data_access_log` (Auditoría), nunca el dato. Agentes (MCP, A2A, asistente): siempre enmascarado.
- Conservación: días por proceso (Legal; sin plazo, se conserva) y supresión a pedido por un admin; ambas anonimizan (borran originales, OCR, lo extraído y los textos que lo citan; queda proceso, fechas y veredicto).
- Telemetría y logs sin datos (excepciones y logs saneados antes de salir); en producción no arranca con un gateway de modelos externo ni con la captura de prompts encendida.
- Fuera: enmascarar lo que va al modelo (es interno y necesita leer el dato), cifrado de columnas, y que el colector de argus reconozca identificadores peruanos (pedido aparte).

## VRT-59 — Búsqueda híbrida
**Why:** el `ILIKE` de VRT-11 no escala, no ordena por relevancia, no tolera un DNI mal leído por el OCR ni encuentra un documento por lo que trata. **Scope:**
- **Qué se indexa:** por documento, los valores extraídos (ya corregidos) y el texto leído de cada página en ventanas solapadas. Cada corrida re-indexa su expediente al terminar, sin hacerla fallar nunca; `scripts/reindex_search.py` indexa lo anterior.
- **Cuatro entradas fusionadas por rango (RRF):** palabras (texto completo en español, sin tildes), escritura parecida (trigramas, tolera un dígito errado), significado (`halfvec` de `qwen3-embedding`) y nombre de archivo. Opcionalmente las reordena un reranker. Embeddings y rerank van directo a prometheus ([ADR-0009](adr/0009-embeddings-y-rerank-directos-a-prometheus.md)); sin ellos se busca por palabras y escritura.
- **Filtros:** unidad (por tenancy) y proceso, combinables con estado, tipo y revisión.
- **Datos personales:** el resultado dice dónde coincidió (datos, página, archivo), nunca qué dice. Buscar sigue reservado a quien puede ver datos, y queda registrado. La anonimización borra los fragmentos y sus vectores.
- **Fuera:** BM25 real (ParadeDB, AGPL) y búsqueda de expedientes como tool del asistente o de MCP.

## VRT-60 — Conectores RENIEC / SUNAT / SBS
**Why:** validar contra fuentes oficiales; desbloquea lo que VRT-15 no pudo. **Scope:** conectores como tools del catálogo. Absorbe VRT-15.

## VRT-61 — Antifraude forense
**Why:** los documentos financieros falsificados con IA crecieron ~4x (2025–2026); validar la coherencia no los detecta. **Scope:** forense del archivo (metadatos, fuentes, píxeles, estructura).

## VRT-62 — Auditoría inmutable y cumplimiento
**Why:** el DS 115-2025-PCM clasifica la evaluación crediticia como de alto riesgo. **Scope:** auditoría con hash encadenado y requisitos de transparencia (confirmar el alcance con Legal).

## VRT-73 — Navegación por tareas y lenguaje de negocio
**Why:** 24 entradas planas en el menú, iguales para todo rol, y estados técnicos (`needs_review`, `payslip`) en pantalla: un operario no sabe por dónde empezar. **Scope:**
- Menú por grupos y rol: Trabajo (Inicio, Expedientes, Revisar con contador, Asistente), Supervisión (Reportes, Auditoría), Administración (Configuración). Pestañas dentro de cada sección.
- Barra superior: búsqueda (VRT-59), «Nuevo expediente», unidad y menú de la persona. Azul corporativo.
- Configuración y Reportes como páginas índice con tarjetas que dicen para qué sirve cada cosa.
- Estados y tipos de documento con nombres de negocio en todas las listas.
- Fuera: el Inicio (VRT-74) y el login y las páginas de detalle (VRT-75).

## VRT-74 — Inicio para decidir, por rol
**Why:** el Inicio contaba documentos sin decir si eso estaba bien ni qué hacer. **Scope:** indicadores con comparación (recibidos, resueltos sin intervención, tiempo hasta decidir, pendientes y su antigüedad), «Requiere tu atención» con su acción, expedientes por día y decisión, motivos de devolución; el operador ve su trabajo del día. Endpoint de métricas.

## VRT-75 — Login y páginas de trabajo
**Why:** el login ponía la contraseña al mismo nivel que la cuenta corporativa, y el expediente abría con una fila de enlaces técnicos en vez de su decisión. **Scope:** ingreso corporativo como acción principal (contraseña plegada); expediente con el veredicto en semáforo, por qué y qué hacer arriba, una acción visible y el resto en «⋯», lo técnico plegado; lista de expedientes con semáforo y nombres de negocio. Fuera: una abstracción de cabecera de página (las cabeceras ya siguen el mismo patrón).

## VRT-76 — Enmascarado legible
**Why:** el texto libre sin mapeo (el resumen de cada documento, una referencia) contaba como personal y sus palabras se tapaban en todo el expediente: «Solicitud de P.», «D. P. de S.». **Scope:** se tapan palabra por palabra solo los nombres de persona (atributo con comparación `person_name`, o un dato del proceso con forma de nombre); un campo sin mapeo se tapa entero donde se cita tal cual. Fuera: marcar campos descriptivos como no personales en el catálogo de tipos.

## VRT-77 — Revisar como cola de trabajo
**Why:** «Revisar» era una lista plana del más nuevo al más viejo: quien revisa saltaba de expediente en expediente y lo que más esperaba quedaba al fondo. **Scope:** campos agrupados por expediente, el que más espera primero (la cola expone `created_at`); filtros por motivo con su conteo; resumen de cuántos y desde cuándo; «todo al día» cuando no hay nada; la tasa del investigador pasa al pie.

## VRT-78 — Documentos con su expediente
**Why:** la lista de documentos no decía de qué expediente era cada uno ni cuándo llegó, y mostraba la confianza de clasificación, un dato técnico. **Scope:** columnas Documento, Tipo, Expediente (enlace), Estado y Llegó; la lista expone `case_ref` y `created_at`.

## VRT-79 — Reglas en una sola lista
**Why:** la página apilaba el formulario de regla nueva siempre abierto y dos tablas, con códigos (`self.payslip_…`, CEL) y jerga («LLM», «stub») en primer plano. **Scope:** una tabla de reglas en vigor (del sistema y creadas aquí) que dice primero qué verifica, con tipo, origen y estado; «Nueva regla» en la cabecera; borradores por revisar arriba; descripciones de las reglas del sistema en lenguaje de negocio.

## VRT-80 — Editor de procesos en tres pasos
**Why:** armar un proceso pedía claves, condiciones CEL, atributos (`ingreso.neto_mensual`), ids de reglas y severidades en inglés. **Scope:** tres pasos (datos del proceso, qué documentos exige, qué comprueba); el identificador del proceso y de cada requisito se genera del nombre; datos, tipos y reglas por su nombre; la condición CEL y el identificador, en «Opciones avanzadas»; barra fija para guardar y publicar.

## VRT-81 — Catálogo de datos y tipos de documento en palabras
**Why:** el catálogo mostraba claves (`persona.dni`, `payslip`), tipos y comparaciones en inglés (`string`, `person_name`), «PII» y CEL; Tipos de documento remitía a la API. **Scope:** al leer, cada dato por su nombre (la clave, tenue), tipos, comparaciones y dato personal en español, el formato como «Se valida»; mapeos con el nombre del tipo, del dato y de a quién pertenece; pestañas y descripciones en lenguaje de negocio. Al editar se siguen viendo los valores guardados.

## VRT-82 — Datos de documentos sin tipo, nombrados en español
**Why:** en un documento sin tipo registrado el modelo inventaba los nombres de los datos en inglés (`loan_amount_requested`, «Borrower Name»), y en Revisar o en el detalle se leían así; al corregirlo, el modelo empezó a distinguir personas por su apellido, lo que pondría datos personales en un rótulo que no se enmascara. **Scope:** la instrucción `extract_generic` y la descripción de la clave piden el nombre en español, con varias personas distinguidas por papel u orden. Los documentos ya leídos conservan sus nombres hasta volver a procesarlos.

## VRT-83 — Nuevo expediente por proceso y reportes en palabras
**Why:** «Nuevo expediente» seguía en el flujo de lotes: sin proceso, con «código de empleado esperado» y pares clave-valor libres. Observaciones, Auditoría y Evaluación mostraban códigos de regla, severidades y estados en inglés, claves de tipo y nombres técnicos de campo. **Scope:** subir crea el expediente con `POST /v1/cases`: proceso, n.º de solicitud, lo que pide el proceso y solo los datos que sus condiciones leen (como el servidor MCP), PDF o fotos. Observaciones y Auditoría muestran el dato por su nombre (`field_label`, el mismo rotulador de Revisar, también para las rutas del catálogo) y dejan la regla y la explicación técnica plegadas. Evaluación habla de conjuntos de prueba; Cargas masivas, de proceso. Fuera: Asistente, Instrucciones al modelo, Catálogo de tools y Probar cambios.

## VRT-84 — Asistente flotante, menú plegable y herramientas de IA en palabras
**Why:** el asistente era una página más del menú: para preguntar había que dejar lo que se estaba viendo y la conversación se perdía al volver. Las páginas de IA hablaban de MCP, suites, «determinista» y claves de proceso. **Scope:** botón flotante redondo con su nombre y atajo (⌘K / Ctrl K) al pasar el cursor en todas las páginas con sesión; panel a la derecha que corre la página solo si a esta le quedan los ~1040 px que asumen sus diseños más anchos (si no, va encima, para no apretar columnas), con la conversación que sobrevive a la navegación, sugerencias según la página, el expediente como etiqueta que se puede quitar, copiar y reintentar; sobre el expediente abierto (o el que la empezó, hasta «Nueva»); «Preguntar al asistente» del expediente lo abre ahí; se quitan la entrada del menú y la ruta `/asistente`. Menú lateral plegable a iconos con su nombre al pasar el cursor, recordado en el navegador. Los expedientes anteriores a las corridas se leen por su propio estado (el asistente los daba por «esperando documentos», sin veredicto). «Herramientas para agentes» («Para otros sistemas», «Sin modelo», «Ficha técnica»); Instrucciones al modelo con conjuntos de prueba y estados en español; Probar cambios con el nombre del proceso.

## VRT-85 — Modo claro, oscuro o como el sistema
**Why:** quienes revisan expedientes de noche trabajaban con la pantalla en blanco; la paleta oscura existía pero nadie podía activarla. **Scope:** «Apariencia» en el menú de la cuenta (Claro / Oscuro / Como el sistema, por defecto el del sistema), recordada en el navegador y aplicada a todas las páginas, avisos e inicio de sesión. Fuera: preferencia guardada por usuario en el servidor.

## VRT-86 — Primeros pasos con avance real
**Why:** la página era una lista de textos iguales: no decía qué estaba hecho ni qué seguía, y el admin debía revisar cada pantalla para saberlo. **Scope:** cada paso se comprueba contra la plataforma (personas y operadores, tipos de documento, catálogo publicado, reglas activas, proceso publicado, expedientes; sistemas conectados opcional; revisión como día a día); en pantallas anchas, columna lateral fija con el avance, el siguiente paso con su acción y quién hace qué (en angostas, el avance arriba y quién hace qué al final); los pasos listos plegados con su dato; quién lo hace y, si no te toca, a quién pedírselo. Fuera: marcar pasos a mano.

## VRT-87 — Procesos en palabras y un solo borrador
**Why:** la lista era una tabla de versiones y el editor hablaba de severidad, «decide» y catálogo semántico; además cada «Guardar borrador» creaba una versión nueva, así que los borradores se apilaban. **Scope:** lista en tarjetas (estado, documentos, comprobaciones, expedientes, conservación, cambios sin publicar con continuar/probar/descartar); editor en dos columnas con «Así decidirá» en vivo y acciones fijas, requisitos con documento/dato y «siempre / si aplica / con condición», agregado rápido de documentos, «si falla» como resultado de negocio y buscador de comprobaciones; se continúa el borrador pendiente, se guarda en su sitio (`PUT` de versión borrador, que descarta sus simulaciones) y se publica en un paso; el nombre cambia sin versión (`PATCH`). Fuera: umbral de confianza por proceso en la interfaz.

## VRT-88 — Tipos de documento en palabras
**Why:** los datos de cada tipo se mostraban por su nombre técnico en inglés («Entity Name», «Member Dni»), y registrar uno nuevo pedía claves, snake_case, esquemas y una lista suelta de mapeos al catálogo. **Scope:** nombre en español por campo (`label`), fuera de la huella de versión y de la extracción, así que cambia sin versión (`PATCH /v1/document-types/{key}/labels`); los 13 tipos actuales nombrados en `domain/field_labels.py` al leer el catálogo; el modelo propone el nombre al registrar; Revisar y Observaciones lo usan. Lista con búsqueda, detectados por registrar primero y ficha con cada dato, su formato y significado; registro en tres pasos con el significado junto a cada dato y lo técnico plegado. Fuera: editar los campos de un tipo existente (sigue siendo una versión nueva).

## VRT-89 — Catálogo de datos en palabras
**Why:** el catálogo se leía como tablas de rutas técnicas (`employee_name → persona.nombre_completo`) y se editaba como una hoja de cálculo de claves; cada «Guardar borrador» creaba una versión nueva. **Scope:** datos agrupados por lo que describen, cada uno con su significado, cómo se compara, privacidad en semáforo y los documentos que lo traen por el nombre de sus campos; vista por documento; personas del expediente; versiones con qué procesos las usan. Edición por diálogo (dato, grupo, persona) sobre un solo borrador que se guarda en su lugar (`PUT /v1/semantic-catalog/versions/{version}`) y se publica desde una barra fija. Fuera: mover un dato de grupo o cambiar su clave (los procesos la usan).

## VRT-90 — Reglas de validación en palabras
**Why:** la lista era una tabla con identificadores técnicos y el alta pedía categoría, campo y atributo en claves internas; una regla creada aquí, una vez desactivada, no volvía a activarse; y si prometheus no tenía sus modelos, la API ni arrancaba, así que ni las reglas se podían listar. **Scope:** reglas agrupadas por con qué comparan, con a quién aplican, gravedad en semáforo, quién la creó y qué procesos la usan, e interruptor en la fila (`POST /validation-rules/{id}/enable`); por revisar con sus casos de prueba en palabras y «Probar y activar»; regla nueva en tres preguntas, con CEL a mano plegado. La API arranca sin modelos, los reintenta cada 30 s y responde 503 claro a lo que los necesita; el worker sigue exigiéndolos.

## VRT-91 — Riesgos y Legal en palabras
**Why:** las lecturas de cada área se veían como una lista larga que se volvía formulario al editar, y no había cómo crear una nueva. **Scope:** un bloque por área con lo que recibe; cada lectura con qué documentos lee y en qué se enfoca, o sus puntos con la importancia en semáforo; crear y editar en un diálogo (documentos a leer como chips, puntos con su importancia). Sin cambios de API: `PUT /v1/lenses/{key}` ya creaba.

## VRT-92 — Probar cambios en palabras
**Why:** el formulario ocupaba la página aunque casi siempre se mira un resultado, las pruebas anteriores eran botones sin decir qué encontraron, y desde un proceso había que volver a elegir proceso y versión. **Scope:** lista de pruebas con su resultado en semáforo (sin cambios, cuántas cambiarían, activa, no terminó) y la elegida al lado: titular, cifras, hoy contra con el cambio con su diferencia, qué cambiaría y los expedientes afectados. Nueva prueba en un diálogo de tres preguntas que abre listo desde un proceso y propone su borrador. Sin cambios de API.

## VRT-93 — Instrucciones al modelo en palabras
**Why:** catorce tarjetas iguales en fila, cada una con su texto, borrador e historial plegados, hacían difícil ver cuál tenía un borrador esperando o cuál usó otra versión un expediente. **Scope:** lista por etapa (leer, comparar, configurar, conversar) con el estado de cada una en semáforo y la elegida al lado: cifras, texto con las partes que completa la plataforma marcadas, borrador con qué cambia, con qué se probó y publicar, e historial con volver a una versión. Proponer un cambio en un diálogo que verifica en vivo que no falte ninguna parte. Abierta desde un expediente, empieza por la instrucción que usó otra versión. Sin cambios de API.

## VRT-94 — Instrucciones al modelo en inglés
**Why:** las instrucciones en español daban la misma exactitud que en inglés, pero el modelo tardaba tres veces más y fallaba más; medido con respaldo `backup/prompts-es`: 69 % vs 69 % de exactitud, 21 vs 7 min por corrida, 3 vs 0 errores del modelo. **Scope:** todas las instrucciones y las descripciones de campos que lee el modelo pasan a inglés, con la indicación de copiar los valores tal como los escribe el documento; todo lo que lee una persona (respuestas, preguntas, motivos, mensajes, resúmenes) sigue en español; las claves de máquina no cambian. Fuera: el carné con dos personas en una página, que en inglés confunde más los datos de cada una.

## VRT-95 — Herramientas para agentes en palabras
**Why:** una tabla de 23 filas con descripciones escritas para agentes (parámetros entre comillas, nombres técnicos) no dejaba ver qué puede hacer un sistema conectado ni qué usa cada agente por dentro. **Scope:** dos fichas que filtran (para otros sistemas / internas), búsqueda y «solo las que usan IA»; bloques por uso con una tarjeta por herramienta: frase de negocio, usa IA o no, consulta o cambia algo, costo en semáforo y quién la usa; el texto para el agente, el nombre y si se puede repetir, plegados. Sin cambios de API.

## VRT-96 — Personas en palabras
**Why:** una tabla con un ícono rojo de borrar en cada fila, y para cambiar el rol de alguien había que quitarlo y volver a crearlo; el alta pedía «Contraseña: solo si es una persona nueva» sin explicar qué hacía cada rol. **Scope:** fichas por rol con lo que puede hacer y cuántos hay (filtran), búsqueda, personas en tarjetas agrupadas por rol; un diálogo para cambiar el rol o quitar de la unidad, de solo lectura para cuentas corporativas; alta con el rol elegido por lo que permite. API: `PATCH /users/{id}` cambia el rol (no el propio ni el de una cuenta corporativa).

## VRT-97 — Sistemas conectados en palabras
**Why:** una tabla con fechas sueltas («Secreto desde: 9/10/26, 2:14 p.m.») no decía si un sistema estaba en uso, y el alta mezclaba en una fila el nombre, una cuota numérica y las credenciales que aparecían debajo. **Scope:** una tarjeta por sistema con su estado en semáforo (en uso, sin uso reciente, aún no se conecta, sin acceso), último uso y cambio de secreto en palabras; conectar en un diálogo: nombre y cuota por opciones, luego las credenciales una sola vez con copiar; el nuevo secreto tras cambiarlo, en el mismo diálogo; los sistemas sin acceso y la guía para su equipo técnico, plegados. Sin cambios de API.

## VRT-98 — Ajuste de las instrucciones de extracción en inglés
**Why:** tras pasar a inglés (VRT-94), la boleta y el carné de extranjería salían por debajo del español: periodo con restos del OCR («ENE 2026 N:1-»), total de descuentos negativo o calculado por el modelo, listas incompletas, y datos de dos personas mezclados en un carné con frentes y reversos en otro orden. **Scope:** cuatro reglas generales en la instrucción de extracción: valor sin texto pegado por el OCR, montos copiados del documento y descuentos en positivo, cada página ligada a su persona por número o nombre (no por orden), y contar las filas de cada lista antes de entregar. Resultado (banco de 4 documentos): boleta 6/6 en 5 de 5 corridas (antes 3–5/6); carné estable en 6/12 (inglés 2–6, español 6–9). Fuera: el emparejamiento del carné, que la instrucción sola no resuelve con el modelo actual.

## VRT-99 — Mensaje claro cuando la IA no responde bien
**Why:** al redactar una regla, si el modelo no entregaba una salida válida en sus intentos, la pantalla recibía un 500 sin explicación. **Scope:** toda la API responde 502 con «La IA no logró dar una respuesta válida esta vez. Inténtalo de nuevo o dilo con otras palabras.», como ya lo hace con 503 cuando falta el modelo. Fuera: reintentar solo.

## VRT-100 — Evaluaciones con el mismo archivo repetido
**Why:** la suite «Correcciones de boletas» tiene tres copias de la misma boleta; al evaluarlas a la vez, la segunda y la tercera chocaban con la petición de la primera aún en curso en el gateway y salían como fallidas, o la corrida quedaba colgada. **Scope:** en una corrida, los casos con el mismo contenido y páginas esperan su turno; los distintos siguen en paralelo. Fuera: la llave de idempotencia de synaptum.

## VRT-101 — Unidades de negocio en palabras
**Why:** el alta era una fila con un identificador técnico y una casilla, renombrar abría un cuadro del navegador, y los grupos de la cuenta corporativa ocupaban la tabla. **Scope:** una tarjeta por unidad con cuántas personas entran (en ámbar si nadie todavía) y «Estás aquí» en la actual; un diálogo para crear (nombre, identificador plegado, en blanco o con ejemplos) que termina mostrando los grupos a crear, y para renombrar o eliminar; los grupos de cada unidad, plegados con copiar. Sin cambios de API.

## VRT-102 — Auditoría en palabras
**Why:** dos tablas anchas con desplazamiento lateral; en los accesos a datos personales, 190 de 220 registros eran borrados automáticos de pruebas que tapaban lo que hicieron las personas, y las correcciones sin motivo no se distinguían. **Scope:** pestañas Correcciones / Datos personales (solo admin); motivos de corrección en barras que filtran, con «Sin motivo registrado» en ámbar; búsqueda; cada registro como una frase (dato, antes → después, documento, quién, motivo) agrupado por día; personas y procesos automáticos por separado, filtro por acción; «ver anteriores» en vez de un tope fijo; modelo e instrucción de cada corrección, plegados. Sin cambios de API.

## VRT-103 — Reversos de documentos de identidad ligados por su número
**Why:** en un archivo con los carnés de dos personas y los reversos en otro orden, el modelo cruzaba el pasaporte y las fechas entre ellas; la instrucción de VRT-98 no bastó. **Scope:** al armar la instrucción de extracción, una página cuya línea legible por máquina (MRZ) empieza con un número impreso en otra página se declara de ese registro, como un hecho; documentos sin esas líneas no cambian. Resultado: carné 12/12 en 2 de 3 corridas (antes 6/12), banco completo 94 % (antes 69 %).

## VRT-104 — Observaciones de validación en palabras
**Why:** una tabla paginada de a 25 donde la misma diferencia entre documentos aparecía una vez por cada documento del expediente, sin decir de qué expediente era ni cuántos errores había en total. **Scope:** fichas de errores, advertencias e informativas con su total, que filtran; filtros de comprobación en chips y de tipo de documento; observaciones agrupadas por expediente (con su nombre y enlace) y dichas una vez con los documentos en que se vieron; los datos que no coinciden entre documentos, en una tabla por expediente (cada dato, y cada valor con los documentos que lo dicen) en vez de los párrafos de la regla de consistencia; «ver anteriores» en vez de páginas; la regla detrás, plegada. API: cada observación trae `case_ref`.

## VRT-105 — Qué hacer con cada observación
**Why:** la página decía lo que no se cumplió pero no qué hacer con eso: la corrección vivía en otra cola y la investigación de la IA solo en el expediente. **Scope:** lista de expedientes con observaciones, una línea cada uno (gravedad, títulos, cuántas por revisar), y el elegido al lado con la guía en una línea; en cada observación, su estado (por revisar, corregida, confirmada sin cambios), «Revisar» en un diálogo con la misma fila de la cola, «Pedir a la IA» y su diagnóstico en dos líneas con «ver más»; para los datos que no coinciden, «Pedir a la IA cuál es el correcto» y «Ver los documentos»; filtro «Por revisar». API: cada observación trae su revisión y su última investigación.

## VRT-106 — Confiabilidad de la lectura en palabras
**Why:** cada dato era una fila ancha con una barra que ocupaba media pantalla, «usar esta medición» quedaba al final, y «¿cuánto podría pasar sin revisión?» repetía tres veces «ningún dato». **Scope:** franja con la medición (elegirla, comprobaciones, si está en uso) y sus acciones; aviso de pocos datos con acceso a medir con más documentos; tres cifras con cuánto se sobreestima el sistema; tablero en semáforo (pueden pasar solos, con cuidado, revisar siempre) con una tarjeta por dato; lo que podría pasar sin revisión en una frase cuando es lo mismo para todo; detalle técnico plegado. Sin cambios de API.

## VRT-107 — Evaluación en palabras
**Why:** dos formularios grandes ocupaban la página principal; en un conjunto, las opciones de prueba eran casillas sueltas en el encabezado, las corridas botones en fila y la comparación un párrafo con cada instrucción cambiada. Además, la comparación devolvía los datos personales sin ocultar, y el enmascarado ocultaba el nombre de cada dato (salía «E.»). **Scope:** conjuntos en tarjetas con datos y tipo en semáforo; nuevo conjunto en un diálogo que elige el camino (correcciones, o tabla en tres pasos); en un conjunto, historial de corridas a la izquierda y la elegida al lado: si mejoró o empeoró y por qué cambio, qué empeoró y qué mejoró (antes → después), cada dato en barras con su nombre del catálogo, cada documento con «leyó → era»; correr en un diálogo con lo que se quiera probar; lo esperado y los modelos, plegados. API: la comparación se enmascara como los resultados y el nombre de cada dato ya no se oculta.
