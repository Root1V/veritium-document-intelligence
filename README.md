# Veritium

**`veritium-document-intelligence`** — plataforma agentica de inteligencia documental.

Veritium clasifica, extrae y **valida** datos de documentos empresariales.
La diferencia no esta en leer campos de un PDF, sino en contrastarlos: cada
dato extraido viaja con su evidencia (pagina, bounding box y texto fuente) y
pasa por un motor de validacion de 6 categorias con reglas configurables en
CEL. Incluye matching difuso de identidad, extraccion agentic acotada y
trazabilidad completa (OTEL + auditoria de correcciones humanas).

El estado de cada feature esta en [`roadmap.md`](roadmap.md); el detalle de
cada item, en [`docs/roadmap.md`](docs/roadmap.md).

## Requisitos

- Python 3.13, [`uv`](https://docs.astral.sh/uv/)
- Docker (Postgres + MinIO via `docker-compose.yml`)
- Prometheus corriendo y un cliente de Veritium en él (client credentials) con
  permiso sobre un modelo de texto y uno de visión. Veritium llega a los
  modelos **solo** por el SDK de axonium y toma de esos permisos qué modelo usa
  en cada rol; nunca despliega ni administra esa infraestructura.

## Arranque rapido

```bash
cp .env.example .env   # completa AXONIUM_CLIENT_ID / AXONIUM_CLIENT_SECRET (cliente de Veritium en prometheus)
docker compose up -d
uv sync --extra docling --extra paddleocr
uv run alembic upgrade head
uv run python scripts/seed_reference_data.py
uv run uvicorn idp.api.app:app --reload
```

## Verificacion

```bash
uv run pytest tests/unit -v                       # no requiere infraestructura externa
uv run pytest tests/integration -v                 # requiere Postgres+MinIO+LLM vivos; se saltan limpiamente si no
uv run python scripts/compare_ocr_backends.py       # compara Docling vs PaddleOCR sobre el corpus de fixtures
uv run python scripts/run_fixture_batch.py          # corre el corpus completo contra la API viva y diffea vs goldens
```

## Estructura

Ver `src/idp/` — dominio (`domain/`), parsing (`parsing/`), clasificacion
(`classification/`), extraccion (`extraction/`, incluye el bucle agentic
acotado en `extraction/agentic/`), motor de validacion de 6 categorias
(`validation/`), revision humana (`review/`), orquestacion (`pipeline/`),
persistencia (`persistence/`), API (`api/`) y observabilidad OTEL
(`observability/`).
