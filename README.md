# Veritium

`veritium-document-intelligence`

Plataforma de inteligencia documental agentica: clasifica, extrae y valida
datos de documentos empresariales (Fase 0: boletas de pago y declaraciones
de seguro de desgravamen), con validacion determinista, matching difuso de
identidad, extraccion agentic acotada y trazabilidad completa (OTEL +
auditoria de correcciones humanas).

Ver el plan completo de arquitectura y roadmap en
`~/.claude/plans/estoy-buscando-hacer-proyecto-iterative-island.md`.

## Requisitos

- Python 3.13, [`uv`](https://docs.astral.sh/uv/)
- Docker (Postgres + MinIO via `docker-compose.yml`)
- Un endpoint OpenAI-compatible ya corriendo para los roles `reasoning` y
  `vision` (p. ej. tu propio proyecto de serving Prometheus, o cualquier
  servidor vLLM/llama.cpp). Este proyecto **nunca** despliega ni administra
  esa infraestructura — solo apunta a ella via configuracion.

## Arranque rapido

```bash
cp .env.example .env   # ajusta REASONING_BASE_URL / VISION_BASE_URL a tus endpoints reales
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
