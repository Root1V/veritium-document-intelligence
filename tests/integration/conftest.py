"""Integration tests need real infrastructure (Postgres/MinIO via
``docker compose up -d``, and a reachable LLM/VLM endpoint — e.g. the user's
own Prometheus serving project). These fixtures skip with a clear reason
instead of failing when that infra isn't available, since this project never
provisions it itself."""

from __future__ import annotations

import contextlib
import socket
import uuid
from collections.abc import AsyncIterator, Iterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import delete

from axonium import DEFAULT_GATEWAY_BASE_URL

from idp.config import Settings
from idp.llm.port import inference_lifespan
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import Base, Membership, Tenant


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    return Settings()


@pytest.fixture(autouse=True)
def default_unit() -> Iterator[None]:
    """What a test does on the database directly, it does for the unit
    ``default`` (VRT-57); its HTTP calls act for their token's unit."""
    with tenancy.acting_for("default"):
        yield


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


@contextlib.asynccontextmanager
async def _throwaway_unit(settings: Settings) -> AsyncIterator[str]:
    key = f"test-{uuid.uuid4().hex[:12]}"
    factory = get_session_factory(settings)
    async with factory() as session:
        session.add(Tenant(key=key, name=f"Prueba {key}"))
        await session.commit()
    try:
        yield key
    finally:
        with tenancy.system():  # cleaning up: every row of that unit, whatever its table
            async with factory() as session:
                for table in reversed(Base.metadata.sorted_tables):
                    if "tenant" in table.c and table.name != "memberships":
                        await session.execute(table.delete().where(table.c.tenant == key))
                await session.execute(delete(Membership).where(Membership.tenant == key))
                await session.execute(delete(Tenant).where(Tenant.key == key))
                await session.commit()


@pytest_asyncio.fixture
async def scratch_unit(live_settings: Settings, require_postgres: None) -> AsyncIterator[str]:
    """A business unit of its own for one test, removed afterwards (with
    whatever the test left in it): isolates it from the dev database's data."""
    async with _throwaway_unit(live_settings) as key:
        yield key


@pytest_asyncio.fixture
async def other_unit(live_settings: Settings, require_postgres: None) -> AsyncIterator[str]:
    """A second throwaway unit, for tests about what one unit sees of another."""
    async with _throwaway_unit(live_settings) as key:
        yield key
