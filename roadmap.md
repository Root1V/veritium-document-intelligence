# Roadmap

Índice. Detalle de cada item en [docs/roadmap.md](docs/roadmap.md).

| ID | Feature | Estado | Descripción |
|---|---|---|---|
| RM-01 | Pipeline agéntico de documentos | done | Ingesta → parsing → clasificación → extracción con grounding citado → validación (6 categorías) → revisión humana. |
| RM-02 | Segmentación + tipos de documento | done | Divide un PDF bundle en documentos lógicos; 12 `DocumentType` tipados + `generic`. |
| RM-03 | Descubrimiento automático de tipos | done | El LLM propone tipos nuevos cuando un documento cae en `generic`; un humano decide, nunca se auto-registra. |
| RM-04 | Módulo web (frontend) | done | Login JWT, dashboard, `/upload`, `/batches/:id`, `/documents/:id` (visor + bounding boxes), `/review`, `/document-types`. |
| RM-05 | Vista de auditoría | done | `/audit` — historial de correcciones. |
| RM-06 | Browser de documentos | done | `/documents` con filtros combinados (estado, tipo, revisión). |
| RM-07 | Métrica de tiempo ahorrado | done | Tarjeta en el dashboard, con supuesto de min/documento configurable. |
| RM-08 | Roles de usuario | done | admin / operador / visor, con enforcement en cada endpoint. |
| RM-09 | Pipeline visual en tiempo real | done | Barra de progreso por documento en `/batches/:id`. |
| RM-10 | Server-Sent Events | done | Reemplaza el polling de 2s por push del servidor. |
| RM-11 | Búsqueda de texto libre | done | En `/documents`, busca nombre de archivo y contenido extraído. |
| RM-12 | Editor de sugerencias de tipo | done | Editar el borrador del LLM antes de aceptar/rechazar un tipo nuevo. |
| RM-13 | Vista de auditoría de validación | done | `/validation` — observaciones de validación cruzando documentos. |
| RM-14 | Motor de reglas configurables (CEL) | done | `/validation-rules` — crear/editar/activar/desactivar reglas sin tocar código. |
| RM-15 | UI de Integraciones | blocked | Falta elegir un sistema externo real — hoy `ExternalSystemPort` es un stub. |
| RM-16 | Corregir layout del visor de documento | done | En `/documents/:id`, el PDF se superpone al panel de resumen/campos extraídos. |
| RM-17 | Corregir bounding box resaltado | todo | Al seleccionar un campo, el cuadro resaltado sobre el PDF aparece desubicado. |
| RM-18 | Columna de página + salto automático | todo | Tabla de campos: columna con la página de cada uno; clic navega el visor a esa página. |
| RM-19 | Persistir nombre/descripción de tipo de documento | todo | Guardar en BD nombre visible y resumen por tipo (hoy solo viven en código); rediseñar `/document-types`. |
| RM-20 | Mejorar columna "Documento" en /audit y /validation | todo | Mostrar nombre del documento + archivo físico como subtítulo tenue, con link al detalle. |
| RM-21 | Resumen del documento en /documents/:id | done | El LLM genera un resumen breve por documento extraído, mostrado antes de la tabla de campos. |
| RM-22 | Renombrar el proyecto a Veritium | done | Repo, README, título de la API y sidebar pasan de "IDP / Intelligent Document Platform" a Veritium. |
