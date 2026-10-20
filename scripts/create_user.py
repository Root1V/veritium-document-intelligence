#!/usr/bin/env python
"""Creates a login user for the frontend — no self-signup (internal tool).
Once at least one "admin" user exists, further users can also be created
from the "Usuarios" page in the UI — this script remains the way to
bootstrap that first admin.
Run: ``uv run python scripts/create_user.py --name "Victor Espiritu" --email victor@example.com --password secret123 --role admin``
Local AI specialist (VRT-63): ``uv run python scripts/create_user.py --name "Especialista IA" --email especialista@example.com --password ia-28af10d1 --role especialista_ia``
"""

from __future__ import annotations

import argparse
import asyncio

from idp.auth.security import hash_password
from idp.config import get_settings
from idp.persistence.db import get_session_factory
from idp.persistence.repositories import UserRepository

ROLES = {"admin", "operador", "visor", "integracion", "especialista_ia"}


async def run(name: str, email: str, password: str, role: str, tenant: str, platform_role: str | None) -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(email)
        if existing is not None:
            if platform_role is not None:  # the platform role is the operator's to grant (VRT-71)
                existing.platform_role = platform_role
                await session.commit()
                print(f"Rol de plataforma de {email}: {platform_role}")
            else:
                print(f"User already exists: {email}")
            return
        user = await repo.create(name=name, email=email, password_hash=hash_password(password), role=role, tenant=tenant)
        user.platform_role = platform_role
        await session.commit()
    print(f"Created user: {name} <{email}> ({role} en {tenant})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="operador", choices=sorted(ROLES))
    parser.add_argument("--tenant", default="default", help="unidad de negocio (scripts/create_tenant.py)")
    parser.add_argument("--platform-role", choices=["admin", "especialista_ia"], help="rol sobre lo que comparten todas las unidades (VRT-71)")
    args = parser.parse_args()
    asyncio.run(run(args.name, args.email, args.password, args.role, args.tenant, args.platform_role))
