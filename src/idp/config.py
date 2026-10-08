"""Central configuration. Everything that was a hardcoded literal in the PoC
(model names, endpoint URLs, thresholds, truncation limits) lives here as a
single ``Settings`` object, sourced from environment variables / ``.env``.

Nothing here deploys or manages model-serving infrastructure — ``reasoning_*``
and ``vision_*`` settings simply point at already-running OpenAI-compatible
endpoints (e.g. the user's own Prometheus serving project, or anything else
speaking the same protocol).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- API ---
    environment: Literal["dev", "test", "prod"] = "dev"

    # --- Auth (JWT) ---
    # HS256 shared-secret signing — adequate for a single-backend internal
    # tool; move to asymmetric keys only if a second service ever needs to
    # verify tokens independently.
    jwt_secret_key: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 480  # 8h — one work shift

    # --- CORS (frontend dev server origin) ---
    cors_allowed_origins: list[str] = ["http://localhost:5180"]

    # --- Database ---
    database_url: str = "postgresql+asyncpg://idp:idp@localhost:5433/idp"

    # --- Object storage (S3-compatible; MinIO locally) ---
    storage_endpoint_url: str = "http://localhost:9002"
    storage_access_key: str = "idp"
    storage_secret_key: str = "idp12345"
    storage_bucket: str = "idp-documents"
    storage_region: str = "us-east-1"

    # --- LLM/VLM: externally-served, OpenAI-compatible endpoints ---
    # Points at whatever already serves the models (e.g. the user's Prometheus
    # project). This project never starts, owns, or manages that server.
    reasoning_base_url: str = "http://localhost:8086/v1"
    reasoning_model: str = "gpt-oss-20b-mxfp4"
    reasoning_api_key: str = "none"

    vision_base_url: str = "http://localhost:8107/v1"
    vision_model: str = "qwen3vl-32B-Q4"
    vision_api_key: str = "none"

    # Whether the endpoint behind reasoning_base_url exposes grammar/JSON-
    # schema-constrained decoding (e.g. vLLM's guided_json). When False,
    # structured output relies entirely on Instructor's reask-on-failure loop.
    llm_supports_guided_json: bool = False

    # Per-request timeout for calls to the externally-served LLM/VLM
    # endpoints. Without an explicit bound, a stalled connection blocks a
    # document's processing indefinitely — confirmed in practice.
    llm_request_timeout_seconds: float = 180.0

    # --- Parsing / OCR backend selection ---
    # "docling" | "paddleocr" — overridable per document type later; Phase 0
    # implements both behind the same ParserBackend protocol and compares
    # them with scripts/compare_ocr_backends.py before fixing a default.
    parser_backend: Literal["docling", "paddleocr"] = "paddleocr"
    ocr_language: str = "es"

    # --- Classification ---
    classification_confidence_threshold: float = 0.6

    # --- Agentic extraction loop ---
    # 6 proved too tight in practice against a real 170-region payslip scan
    # with a small local reasoning model exploring text regions one call at
    # a time (read_text_region calls are cheap but still cost a turn) —
    # raised after live testing against Prometheus-served gpt-oss-20b.
    extraction_max_turns: int = 20

    # --- Review routing ---
    review_confidence_threshold: float = 0.75

    # --- Entity matching (fuzzy validation, categories b/d) ---
    entity_match_high_threshold: float = 0.90
    entity_match_low_threshold: float = 0.60

    # --- Observability ---
    otel_service_name: str = "idp"
    otel_console_export: bool = True

    # --- Webhooks (VRT-28) ---
    # Fernet key that encrypts webhook signing secrets at rest. Required to
    # register an endpoint. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secrets_encryption_key: SecretStr | None = None
    # The dispatcher runs inside the API process until the worker exists
    # (VRT-26); deliveries are claimed with SKIP LOCKED, so several
    # instances can run it at once.
    webhook_dispatcher_enabled: bool = True
    webhook_dispatch_interval_seconds: float = 2.0
    webhook_request_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
