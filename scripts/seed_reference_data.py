#!/usr/bin/env python
"""Seeds the minimal ``reference_employees`` table (category d validation)
with the employees appearing in the fixture corpus, so
``EmployeeCodeExistsInReferenceData``/``EmployeeNameExistsInReferenceData``
have real data to check against. The master is each business unit's own
(VRT-57). Run: ``uv run python scripts/seed_reference_data.py [--tenant pymes]``
"""

from __future__ import annotations

import argparse
import asyncio

from idp.config import get_settings
from idp.persistence import tenancy
from idp.persistence.db import get_session_factory
from idp.persistence.models import ReferenceEmployee
from sqlalchemy import select

SEED_EMPLOYEES = [
    ("70349965", "Salas Siguas, Katerin Karola"),  # boleta_pagos1.png (DNI used as code — no explicit employee_code on the document)
    ("21441884", "Negron Nuñez, Milagros Elizabeth"),  # boleta_pagos2.png
]


async def run(tenant: str) -> None:
    settings = get_settings()
    factory = get_session_factory(settings)
    with tenancy.acting_for(tenant):
        async with factory() as session:
            for code, full_name in SEED_EMPLOYEES:
                existing = await session.execute(select(ReferenceEmployee).where(ReferenceEmployee.employee_code == code))
                if existing.scalar_one_or_none() is None:
                    session.add(ReferenceEmployee(employee_code=code, full_name=full_name, active=True))
            await session.commit()
    print(f"Seeded {len(SEED_EMPLOYEES)} reference employee(s) in {tenant}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="default", help="unidad de negocio")
    asyncio.run(run(parser.parse_args().tenant))
