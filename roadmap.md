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
| VRT-31 | Observabilidad con argus | done | OTLP hacia argus, una traza de punta a punta, costo por expediente. |

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
| VRT-69 | Agente de extracción eficiente | done | Medir tokens por turno y recortar lo que el agente reenvía; hoy es el 70–90% del tiempo de cada documento. |
| VRT-70 | Lectura (OCR) más rápida en el mismo hardware | done | Runtime y tamaño de modelo del OCR medidos por tiempo y precisión; hoy 5–22 s por página. |

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
| VRT-54 | Asistente del usuario | done | Asistente sobre synaptum que usa el MCP de Veritium con el token de la persona. |
| VRT-55 | Permisos de tools con Cedar | done | Cedar de aeon sobre las tools expuestas y las de terceros (aeon lo entregó: `AEON-VRT-002`). |
| VRT-66 | Agente investigador de discrepancias | done | Ante cada hallazgo, investiga con tools y le deja al revisor diagnóstico, corrección sugerida y evidencia; no decide. |
| VRT-67 | Autovalidación de la extracción | done | El agente de extracción revisa su borrador con las reglas propias del documento y corrige antes de entregar. |
| VRT-68 | Clasificación con escalamiento agéntico | todo | Una llamada para lo claro; un agente que revisa páginas cuando la confianza es baja o el PDF mezcla documentos. |

## F7 — Hardening y producción

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-56 | Ruta de inferencia gobernada | blocked | synaptum → aeon-modelgw → prometheus, con presupuestos y costo por corrida. Espera `VRT-AEON-008`. |
| VRT-57 | SSO OIDC y multi-tenant | done | Identidad corporativa y aislamiento por tenant. |
| VRT-58 | PII y retención | done | Enmascaramiento según la clase PII semántica; políticas de retención y borrado. |
| VRT-59 | Búsqueda híbrida | done | Por palabras, escritura parecida y significado, en Postgres con halfvec. |
| VRT-60 | Conectores RENIEC / SUNAT / SBS | todo | Validación contra fuentes oficiales como tools. |
| VRT-61 | Antifraude forense | todo | Detección de documentos alterados o generados con IA. |
| VRT-62 | Auditoría inmutable y cumplimiento | todo | Hash encadenado y requisitos del DS 115-2025-PCM. |
| VRT-71 | Administración de plataforma y unidad en blanco | done | Lo compartido lo cambia el equipo de plataforma; unidades vacías; primeros pasos. |
| VRT-72 | Borrado físico y lógico | done | «Eliminar» en cada pantalla: lo que nadie usó se borra con sus archivos; lo usado se archiva; limpieza técnica a 30 días. |

## F8 — Experiencia de uso

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| VRT-73 | Navegación por tareas y lenguaje de negocio | done | Menú agrupado por rol, barra superior con búsqueda, configuración y reportes en páginas índice, estados en español. |
| VRT-74 | Inicio para decidir, por rol | done | Indicadores con su comparación, lo que requiere atención y gráficos con métricas reales. |
| VRT-75 | Login y páginas de trabajo | done | Ingreso corporativo primero; expediente con su decisión en semáforo arriba y lo técnico plegado. |
| VRT-76 | Enmascarado legible | done | Los nombres se tapan palabra por palabra; las palabras del negocio («préstamo», «seguro») ya no. |
| VRT-77 | Revisar como cola de trabajo | done | Campos agrupados por expediente, el que más espera primero, con filtros rápidos y «todo al día». |
| VRT-78 | Documentos con su expediente | done | Cada documento con su expediente y cuándo llegó; sin la confianza técnica. |
| VRT-79 | Reglas en una sola lista | done | Cada regla dice qué verifica en palabras; «Nueva regla» se abre al pedirla; el código técnico, tenue. |
| VRT-80 | Editor de procesos en tres pasos | done | Datos del proceso, qué documentos exige y qué comprueba, con nombres de negocio y lo técnico plegado. |
| VRT-81 | Catálogo de datos y tipos de documento en palabras | done | Cada dato y mapeo por su nombre; tipos, comparaciones y clase de dato personal en español. |
| VRT-82 | Datos de documentos sin tipo, nombrados en español | done | El modelo nombra cada dato como lo leería una persona, sin datos de nadie en el nombre. |
| VRT-83 | Nuevo expediente por proceso y reportes en palabras | done | Subir elige el proceso y pide solo sus datos; observaciones, auditoría y evaluación sin jerga. |
| VRT-84 | Asistente flotante, menú plegable y herramientas de IA en palabras | done | El asistente acompaña en todas las páginas; el menú se pliega a iconos; IA sin jerga. |
| VRT-85 | Modo claro, oscuro o como el sistema | done | Cada persona elige la apariencia desde su menú, para trabajar de noche. |
| VRT-86 | Primeros pasos con avance real | done | Cada paso se comprueba solo, muestra el avance y lleva al siguiente. |
| VRT-87 | Procesos en palabras y un solo borrador | done | Tarjetas por proceso; editor con vista previa de cómo decide y borrador que se guarda en su sitio. |
| VRT-88 | Tipos de documento en palabras | done | Cada dato con su nombre en español, formato y significado; registrar un tipo en tres pasos. |
| VRT-89 | Catálogo de datos en palabras | done | Cada dato con su significado, privacidad y documentos que lo traen; se edita con un clic y un solo borrador. |
| VRT-90 | Reglas de validación en palabras | done | Reglas agrupadas por con qué comparan, interruptor en su sitio y regla nueva en tres preguntas. |
| VRT-91 | Riesgos y Legal en palabras | done | Un bloque por área, lecturas en tarjetas con su importancia en colores, y crear o editar en un diálogo. |
| VRT-92 | Probar cambios en palabras | done | Pruebas en una lista con su resultado en semáforo; cada una con cifras, hoy contra con el cambio, y nueva prueba en tres preguntas. |
| VRT-93 | Instrucciones al modelo en palabras | done | Lista por etapa con su estado, detalle en pestañas (texto, borrador, historial) y cambio propuesto en un diálogo que verifica lo obligatorio. |
| VRT-94 | Instrucciones al modelo en inglés | done | Lo que se le pide al modelo, en inglés; lo que lee una persona (respuestas, preguntas, motivos, mensajes), en español. |
| VRT-95 | Herramientas para agentes en palabras | done | Bloques por uso (abrir expedientes, consultar, Riesgos y Legal, cada agente), una frase de negocio por herramienta y lo técnico plegado. |
| VRT-96 | Personas en palabras | done | Fichas por rol con lo que puede hacer, personas en tarjetas por rol, cambiar el rol sin borrar y agregar en un diálogo claro. |
| VRT-97 | Sistemas conectados en palabras | done | Cada sistema en una tarjeta con su estado en semáforo y «último uso hace…»; conectar en un diálogo de dos pasos; sin acceso y guía técnica plegados. |
| VRT-98 | Ajuste de las instrucciones de extracción en inglés | done | Valor limpio sin restos del OCR, totales copiados y en positivo, varias personas por número y no por página, y contar las filas de cada lista. |
| VRT-99 | Mensaje claro cuando la IA no responde bien | done | Si el modelo no entrega una respuesta válida, la persona lee qué hacer en vez de un error 500. |
| VRT-100 | Evaluaciones con el mismo archivo repetido | done | Las copias de un mismo archivo en una suite se evalúan una tras otra y reciben la respuesta ya generada, en vez de fallar. |
| VRT-101 | Unidades de negocio en palabras | done | Una tarjeta por unidad con cuántas personas entran (en ámbar si nadie), y crear, renombrar o eliminar en un diálogo que termina en los grupos a crear. |
| VRT-102 | Auditoría en palabras | done | Correcciones y accesos a datos personales en pestañas, cada registro como una frase agrupada por día; sin motivo en ámbar; procesos automáticos aparte. |
| VRT-103 | Reversos de documentos de identidad ligados por su número | done | La plataforma dice al modelo a qué carné pertenece cada reverso, leyendo el número de su línea con «<», en vez de dejarlo adivinar por el orden. |
| VRT-104 | Observaciones de validación en palabras | done | Errores, advertencias y notas en fichas que filtran, observaciones agrupadas por expediente y dichas una vez con todos sus documentos. |
| VRT-105 | Qué hacer con cada observación | done | Lista de expedientes y el elegido al lado; cada observación dice si está por revisar, y se revisa ahí mismo o se pide a la IA. |
| VRT-106 | Confiabilidad de la lectura en palabras | done | Estado de la medición y su uso arriba, cuánto se sobreestima el sistema, y los datos en un tablero de semáforo de tres columnas. |
| VRT-107 | Evaluación en palabras | done | Conjuntos en tarjetas con su resultado en semáforo, crear y correr en diálogos, y cada conjunto con su historial de corridas y la elegida al lado. |
| VRT-108 | Revisar en palabras | done | Expedientes en lista y el elegido al lado; cada dato con lo leído, su motivo en semáforo, la sugerencia de la IA, «Corregir» o «Es correcto». |
| VRT-109 | Expedientes, documentos y cargas masivas en palabras | done | Decisiones en fichas que filtran, una línea por expediente o documento, cargas en tarjetas con su resultado en una barra, y nueva carga en un diálogo. |
| VRT-110 | Detalle del expediente en palabras | done | La decisión con qué hacer y cuánto hay detrás, lo que pide el proceso, los datos por persona con los que no coinciden primero, y observaciones sin códigos. |
| VRT-111 | Inicio para decidir | done | Conclusiones con su acción, cómo terminan los expedientes y por canal, documentos que más revisión piden y cuánto espera la cola. |
