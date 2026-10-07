# ADR-0003 · Ejecución durable de expedientes sobre aeon con un nodo de actividad externa

**Estado:** aceptada · 2026-10-07 · depende de `VRT-AEON-001` (canal de equipos)

## Contexto
- Hoy cada expediente corre **en secuencia** dentro de `BackgroundTasks` de FastAPI (`pipeline/orchestrator.py`). Si el proceso cae, el expediente se pierde, y un expediente de 40 documentos no se paraleliza.
- El ecosistema ya tiene **aeon** (ejecución durable sobre Temporal, más gobierno). Pero hoy su motor de grafos no puede ejecutar pasos propios de otra plataforma: la única hoja es `tool_call` (con ejecutores Go), tiene un timeout fijo de 10 s y una sola task queue. Además, su "Modo A" está congelado.

## Decisión
- Veritium define un **`CaseExecutionPort`**. Su adaptador **`AeonExecutor`** genera un grafo por corrida: `start_run → parallel[process_document × N] → evaluate_case → finish_run`, y lo envía a `POST /runs` de aeon.
- Cada nodo es una **actividad externa** (capacidad genérica solicitada a aeon, A-1) ejecutada por el **worker de Veritium**, en una task queue por carril (`veritium-online` / `-backoffice` / `-bulk`). Así la task queue hace de prioridad.
- Las actividades son **idempotentes** y reciben argumentos estáticos (`case_id`, `run_id`, `document_id`). El estado vive en la BD de Veritium, así que no hace falta pasar datos entre nodos, ni que aeon exponga resultados, ni colas por run.
- Hasta que A-1 se entregue, un **`InProcessExecutor` interino** (paralelismo acotado, **no durable**) permite avanzar el resto de F1.

## Alternativas consideradas
- **Temporal propio en Veritium:** descartada por la decisión de construir sobre el ecosistema.
- **Modo B de aeon** (todo el expediente en una actividad de interop, con el journal de synaptum): queda como **plan B** si A-1 se rechaza. Tiene menos granularidad: la durabilidad es por paso del journal, no por documento.

## Consecuencias
- VRT-26 no cierra hasta que A-1 esté entregado; mientras tanto puede pasar a `blocked`.
- La frontera de determinismo sigue el ADR-0001 de aeon: toda la E/S va en actividades.

## Acordado con aeon (canal `VRT-AEON-001` / `VRT-AEON-002`, 2026-10-07)
- **Instancia propia de aeon para Veritium.** En un despliegue compartido, el ledger de costos, la deduplicación y los checkpoints no se aíslan por tenant; un namespace de Temporal aparte no lo resuelve.
- **El bundle de Cedar lo escribe Veritium,** con guardas `resource is ExternalActivity`; ningún permit se expresa solo por nombre.
- **Heartbeat:** es obligación de nuestras actividades, con un intervalo menor que el `heartbeat_seconds` del nodo.
- **Los args estáticos son regla, no limitación,** porque mantienen computables antes del dispatch el recurso Cedar y el hash de aprobación (que incluye la task queue).
- **Se retira el plan B** (Modo B): perdería paralelismo y reanudación por paso.
