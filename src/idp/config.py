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

    # --- Inference (VRT-29): synaptum → axonium → prometheus's gateway ---
    # Model ids are prometheus registry ids, and the client_credentials pair
    # is Veritium's prometheus client (scopes model:<id>). axonium knows the
    # gateway's URL.
    reasoning_model: str = "gpt-oss-20b-mxfp4"
    vision_model: str = "qwen3vl-30b-a3b"
    axonium_client_id: str | None = None
    axonium_client_secret: SecretStr | None = None

    # Per-request timeout for calls to the externally-served LLM/VLM
    # endpoints. Without an explicit bound, a stalled connection blocks a
    # document's processing indefinitely — confirmed in practice.
    llm_request_timeout_seconds: float = 180.0
    # Ceiling on what one model call may generate. Without it a runaway
    # generation (a repetition loop) runs for many minutes, and a retry with
    # the same idempotency key waits for it instead of failing. A truncated
    # answer never validates, so it ends in human review, not in a hang.
    llm_max_output_tokens: int = 8192

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

    # --- Case execution (VRT-26) ---
    # "in_process": the API runs the case itself (no durability; for
    # development). "aeon": the case runs as an aeon graph whose steps are
    # executed by Veritium's worker (python -m idp.worker).
    case_executor: Literal["in_process", "aeon"] = "in_process"
    case_max_parallel_documents: int = 3
    # aeon (Veritium's own deployment: scripts/aeon_dev.sh). The token is the
    # bearer of the "veritium-api" caller; setup writes it to .env.
    aeon_runcontroller_url: str = "http://127.0.0.1:9414"
    aeon_api_token: SecretStr | None = None
    aeon_agent_ref: str = "veritium-case-run@1.0.0"
    aeon_request_timeout_seconds: float = 10.0
    # The worker (python -m idp.worker): Temporal of the aeon deployment, how
    # many steps each lane's queue runs at once, and how often it checks aeon
    # for runs that failed before reaching evaluation.
    temporal_address: str = "localhost:7243"
    temporal_namespace: str = "default"
    worker_lane_concurrency: dict[str, int] = {"online": 4, "backoffice": 2, "bulk": 1}
    worker_reconcile_interval_seconds: float = 30.0

    # --- Webhooks (VRT-28) ---
    # Fernet key that encrypts webhook signing secrets at rest. Required to
    # register an endpoint. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secrets_encryption_key: SecretStr | None = None
    # The dispatcher runs inside the API process; deliveries are claimed
    # with SKIP LOCKED, so several instances can run it at once.
    webhook_dispatcher_enabled: bool = True
    webhook_dispatch_interval_seconds: float = 2.0
    webhook_request_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
