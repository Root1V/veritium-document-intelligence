# Roadmap — detalle

Una sección por item de [roadmap.md](../roadmap.md). Sin bitácora de cambios — eso vive en los commits.

## RM-01 — Pipeline agéntico de documentos
Done. Commit `b0d98c3`.

## RM-02 — Segmentación + tipos de documento
Done. Commits `af76c32`, `9797a2f`, `f6f71fb`.

## RM-03 — Descubrimiento automático de tipos
Done. Commit `ea42c4b`.

## RM-04 — Módulo web (frontend)
Done. Commits `0bda1ab`, `d4cdc8f`.

## RM-05 — Vista de auditoría
**Why:** `audit_log` ya se llenaba en cada corrección desde RM-01; faltaba una ruta que lo expusiera.
**Scope:** solo lectura, sin filtros. Commit `f7d33a3`.

## RM-06 — Browser de documentos
**Why:** el dashboard solo mostraba unos pocos documentos recientes, sin forma de filtrar el corpus completo.
**Scope:** filtros por estado/tipo/revisión, combinables. Sin búsqueda de texto (eso es RM-11). Commit `18d5ccd`.

## RM-07 — Métrica de tiempo ahorrado
**Why:** pedido explícito, con la condición de que el supuesto (min/documento) fuera configurable y visible, no un número inventado.
**Scope:** una tarjeta en el dashboard, cálculo simple sobre documentos completados. Commit `7a6529c`.

## RM-08 — Roles de usuario
**Why:** hasta este punto cualquier usuario autenticado podía hacer cualquier acción; se necesitaba distinguir quién puede ejecutar vs. solo ver.
**Scope:** tres roles (admin/operador/visor), enforcement en cada endpoint mutante, no solo en la UI. No incluye permisos granulares por recurso. Commit `e265f55`.

## RM-09 — Pipeline visual en tiempo real
**Why:** `/batches/:id` solo mostraba "procesando" sin detalle de en qué etapa estaba cada documento.
**Scope:** barra de progreso con las etapas reales del pipeline (parsing/clasificando/extrayendo/validando). Commit `4d0f397`.

## RM-10 — Server-Sent Events
**Why:** el polling de 2s generaba una petición nueva por cliente cada 2s; SSE deja que el servidor empuje solo cuando hay cambio real.
**Scope:** reemplaza el polling en `/batches/:id`. No se extendió a otras vistas. Commit `4734018`.

## RM-11 — Búsqueda de texto libre
**Why:** los filtros de RM-06 no cubrían "encontrar un documento por su contenido".
**Scope:** busca nombre de archivo y valores extraídos, combinable con los filtros existentes. Commit `0e126c5`.

## RM-12 — Editor de sugerencias de tipo
**Why:** antes solo se podía aceptar/rechazar una sugerencia del LLM tal cual — sin forma de corregir un campo mal nombrado sin rechazar toda la propuesta.
**Scope:** edita el borrador (campos, nombre) mientras sigue pendiente. Nunca genera código ni registra el tipo — eso sigue siendo un cambio de código deliberado. Commit `c2675b4`.

## RM-13 — Vista de auditoría de validación
**Why:** los `validation_issues` ya se persistían por cada regla que no pasaba, sin ninguna vista que los cruzara entre documentos.
**Scope:** lista filtrable por categoría/severidad/tipo. Solo lectura. Commit `988b5aa`.

## RM-14 — Motor de reglas configurables (CEL)
**Why:** se pidió poder agregar/modificar/desactivar reglas de validación sin depender de un desarrollador. Generar Python real desde la web se descartó por riesgo de seguridad (ejecución de código no revisado); CEL (lenguaje sandboxed de Google, sin efectos secundarios) permite que una regla activada se ejecute de inmediato sin ese riesgo.
**Scope:** cubre categorías `self`/`request_input`/`reference_data` (comparaciones puras de campos). `cross_document` (fuzzy-matching + LLM) y `external_system` (red) siguen siendo código — CEL no puede expresar esa lógica de forma segura. Incluye activar/desactivar cualquier regla, incluidas las hardcodeadas. Commits `ea77e56`, `d5693a6`.

## RM-15 — UI de Integraciones
**Why:** el dashboard de referencia original incluía una sección de integraciones; no se construyó porque no hay ningún sistema externo real conectado detrás.
**Scope:** bloqueado hasta elegir un sistema real (`ExternalSystemPort` en `src/idp/validation/ports.py` es hoy un stub que siempre responde "no verificado"). Requiere: elegir el sistema, construir el adaptador real, y solo entonces la UI tiene algo que mostrar.

## RM-16 — Corregir layout del visor de documento
**Why:** reportado por el usuario probando `/documents/:id` — react-pdf renderizaba a un ancho fijo en px, y un CSS Grid item no se encoge por debajo del ancho intrínseco de su contenido salvo que se le indique, así que en ventanas angostas el PDF desbordaba su columna.
**Scope:** `PdfViewer` mide su contenedor con `ResizeObserver` y renderiza al ancho real disponible; `min-w-0` en ambas columnas del grid como defensa adicional. Commit `df53ced`.

## RM-17 — Corregir bounding box resaltado
**Why:** reportado por el usuario — al hacer clic en un campo (o varios) para ver dónde se extrajo, el cuadro que se dibuja sobre el PDF aparece desubicado y no coincide con el valor real extraído.
**Scope:** corregir el cálculo de posición del overlay (probablemente un desfase en cómo se escala el bbox normalizado contra el tamaño renderizado de la página).

## RM-18 — Columna de página + salto automático
**Why:** la tabla de campos extraídos no indica en qué página del PDF está cada campo; seleccionar un campo de otra página no mueve el visor hacia ella.
**Scope:** agregar una columna "Página" al inicio de la tabla. Al hacer clic en un campo de otra página, el visor debe navegar a esa página y resaltar el campo — depende de que RM-17 esté resuelto para que el resaltado sea correcto.

## RM-19 — Persistir nombre/descripción de tipo de documento
**Why:** hoy el catálogo de tipos (`/document-types`, "Plantillas") se arma leyendo constantes de código (`TYPE_DESCRIPTIONS`, `SCHEMA_BY_DOCUMENT_TYPE`); el usuario quiere que el nombre visible y la descripción de cada tipo (ej. `loan_payment_schedule` → "Cronograma de Pagos") vivan en la base de datos, no solo en código.
**Scope:** agregar almacenamiento en BD para nombre/descripción por tipo de documento; mejorar el diseño del listado en `/document-types`. Definir al implementar: tabla nueva de tipos vs. otra estructura, y si el "nombre del documento" que pide RM-20 sale de aquí.

## RM-20 — Mejorar columna "Documento" en /audit y /validation
**Why:** hoy esas tablas muestran un link genérico o el nombre físico del PDF, sin un nombre legible del documento. Depende de RM-19 para tener de dónde sacar ese nombre.
**Scope:** mostrar el nombre del documento, con el nombre físico del PDF debajo en texto tenue como subtítulo; el nombre enlaza al detalle del documento. Mismo patrón en ambas páginas — candidato a un componente compartido.

## RM-21 — Resumen del documento en /documents/:id
**Why:** pedido por el usuario validando RM-16 — antes de la tabla de campos extraídos quería un resumen breve de qué trata el documento. Se evaluaron dos opciones (descripción genérica del tipo, ya disponible hoy, vs. un resumen real por documento) y el usuario eligió la segunda pese al mayor esfuerzo. `GenericSchema` ya tenía un campo `summary` — solo faltaba replicarlo en los 12 esquemas tipados.
**Scope:** agrega `summary: Extracted[str] | None` a 11 de los 12 esquemas (`email_correspondence` ya tenía `body_summary` con el mismo propósito — no se duplicó); `GenericSchema` ya lo tenía. La extracción agéntica es 100% schema-driven, no hizo falta tocar los extractores. Frontend: extrae `summary`/`body_summary` de la grilla de campos y lo muestra como bloque de texto aparte, arriba de la tabla. Documentos ya extraídos antes de este cambio no tienen resumen (sin backfill). Commit `e4ea81e`.

## RM-22 — Renombrar el proyecto a Veritium
**Why:** el repo era el único de los proyectos recientes del autor que no seguía su propio patrón de nombres (`<codename clásico>-<dominio>-<tipo>`, como `argus-observability-platform` o `aerarium-agentic-banking`); `agentic-doc-intelligence-platform` era puramente descriptivo y se solapaba con `mercatus-agentic-payments`. *Veritium* (de *veritas*) reclama el diferenciador real: la plataforma no solo extrae campos, los contrasta y deja traza verificable de cada dato.
**Scope:** repo GitHub → `veritium-document-intelligence` (con su remote); branding visible en `README.md`, el `title` de FastAPI, el `<title>` del frontend y el logo del sidebar. Fuera de alcance por diseño: el paquete Python sigue siendo `idp` (renombrarlo tocaría todo el backend sin beneficio visible), y `docker-compose.yml` conserva usuario/BD/volúmenes `idp` — renombrarlos obligaría a recrear los volúmenes y se perdería la base local.
