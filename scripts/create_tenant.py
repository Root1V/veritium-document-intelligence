#!/usr/bin/env python
"""Registers a business unit (VRT-57) and gives it the seed processes.
Units are registered by the operator, never created by a sign-in: an
identity-provider group naming an unregistered unit grants nothing.
Run: ``uv run python scripts/create_tenant.py pymes "Banca Pymes"``
"""

from __future__ import annotations

import argparse
import asyncio

from idp.config import get_settings
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import Tenant
from idp.persistence.repositories import ProcessProfileRepository


async def run(key: str, name: str) -> None:
    async with get_session_factory(get_settings())() as session:
        if await session.get(Tenant, key) is None:
            session.add(Tenant(key=key, name=name))
            await session.commit()
            print(f"Unidad registrada: {name} ({key})")
        else:
            print(f"La unidad ya existe: {key}")
        with tenancy.acting_for(key):
            await ProcessProfileRepository(session).ensure_seed()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("key", help="identificador: minúsculas, dígitos y guiones")
    parser.add_argument("name", help="nombre que ven las personas")
    args = parser.parse_args()
    if not tenancy.valid_key(args.key):
        parser.error("el identificador admite minúsculas, dígitos y guiones")
    asyncio.run(run(args.key, args.name))
