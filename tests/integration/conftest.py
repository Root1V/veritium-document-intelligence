"""Integration tests need real infrastructure (Postgres/MinIO via
``docker compose up -d``, and a reachable LLM/VLM endpoint — e.g. the user's
own Prometheus serving project). These fixtures skip with a clear reason
instead of failing when that infra isn't available, since this project never
provisions it itself."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio

from axonium import DEFAULT_GATEWAY_BASE_URL

from idp.config import Settings
from idp.llm.port import inference_lifespan


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def require_postgres(live_settings: Settings) -> None:
    url = urlparse(live_settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    if not _port_open(url.hostname or "localhost", url.port or 5432):
        pytest.skip(f"Postgres no alcanzable en {url.hostname}:{url.port} (uv run docker compose up -d postgres)")


@pytest.fixture(scope="session")
def require_minio(live_settings: Settings) -> None:
    url = urlparse(live_settings.storage_endpoint_url)
    if not _port_open(url.hostname or "localhost", url.port or 9000):
        pytest.skip(f"MinIO no alcanzable en {url.hostname}:{url.port} (docker compose up -d minio)")


@pytest.fixture(scope="session")
def require_prometheus() -> None:
    url = urlparse(DEFAULT_GATEWAY_BASE_URL)
    if not _port_open(url.hostname or "localhost", url.port or 80):
        pytest.skip(f"gateway de prometheus no alcanzable en {DEFAULT_GATEWAY_BASE_URL}")


@pytest_asyncio.fixture
async def inference_port(live_settings: Settings) -> AsyncIterator[None]:
    """Opens the InferencePort (VRT-29) on the test's event loop, as the
    API's lifespan and the worker do; ASGITransport does not run lifespans."""
    if not live_settings.axonium_client_id or live_settings.axonium_client_secret is None:
        pytest.skip("faltan AXONIUM_CLIENT_ID / AXONIUM_CLIENT_SECRET (credenciales de prometheus) en .env")
    async with inference_lifespan(live_settings):
        yield
