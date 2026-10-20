"""Corporate sign-in (VRT-57), from the claims the provider vouched for to
the person and their units, against real Postgres: groups grant units and
roles, an unregistered unit or an unknown role grants nothing, a later
sign-in replaces what the provider gave and leaves alone what Veritium
manages, and an e-mail only joins an existing account when the provider
verified it. (The provider round trip itself is checked live against the
development Keycloak.)"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from idp.auth.oidc import SignInFailed, platform_role_from, sign_in, units_from
from idp.auth.security import hash_password
from idp.persistence.db import get_session_factory
from idp.persistence.models import Membership, User
from idp.persistence.repositories import UserRepository

pytestmark = [pytest.mark.usefixtures("require_postgres")]
ISSUER = "https://idp.example.com/realms/prueba"


def test_the_platform_group_is_a_role_and_not_a_unit(live_settings):
    claims = {"groups": ["veritium:plataforma:admin", "veritium:pymes:operador"]}
    assert units_from(live_settings, claims) == {"pymes": "operador"}, "«plataforma» is never a unit"
    assert platform_role_from(live_settings, claims) == "admin"
    assert platform_role_from(live_settings, {"groups": ["veritium:plataforma:especialista_ia"]}) == "especialista_ia"
    assert platform_role_from(live_settings, {"groups": ["veritium:plataforma:visor", "otra:plataforma:admin"]}) is None


def test_groups_name_a_unit_and_a_role(live_settings):
    claims = {"groups": ["veritium:pymes:operador", "/veritium:pymes:admin", "veritium:retail:jefe", "otra-app:pymes:admin", "veritium:retail:visor"]}
    assert units_from(live_settings, claims) == {"pymes": "admin", "retail": "visor"}  # the broader role wins; unknown ones grant nothing
    assert units_from(live_settings, {"groups": "veritium:pymes:admin"}) == {}  # not a list


async def _memberships(session, user_id) -> dict[str, tuple[str, str]]:
    rows = (await session.scalars(select(Membership).where(Membership.user_id == user_id))).all()
    return {m.tenant: (m.role, m.source) for m in rows}


@pytest.mark.asyncio
async def test_sign_in_creates_the_person_with_their_units(live_settings, scratch_unit, other_unit):
    factory = get_session_factory(live_settings)
    sub, email = uuid.uuid4().hex, f"test-sso-{scratch_unit}@example.com"
    claims = {"iss": ISSUER, "sub": sub, "email": email, "email_verified": True, "name": "Ana Torres",
              "groups": [f"veritium:{scratch_unit}:operador", f"veritium:{other_unit}:visor", "veritium:no-existe:admin"]}
    try:
        async with factory() as session:
            user = await sign_in(live_settings, session, claims)
            await session.commit()
            assert user.subject == f"{ISSUER} {sub}" and user.password_hash is None and user.name == "Ana Torres"
            assert await _memberships(session, user.id) == {scratch_unit: ("operador", "idp"), other_unit: ("visor", "idp")}

            # Veritium gives her a role in the other unit itself; the provider then takes the first unit away.
            await UserRepository(session).set_membership(user.id, other_unit, "admin")
            await session.commit()
            again = await sign_in(live_settings, session, {**claims, "groups": [f"veritium:{other_unit}:operador"]})
            await session.commit()
            assert again.id == user.id
            assert await _memberships(session, user.id) == {other_unit: ("admin", "local")}

            # The provider grants the platform role and takes it away (VRT-71).
            assert (await sign_in(live_settings, session, {**claims, "groups": ["veritium:plataforma:admin"]})).platform_role == "admin"
            assert (await sign_in(live_settings, session, {**claims, "groups": []})).platform_role is None
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()


@pytest.mark.asyncio
async def test_an_email_joins_a_local_account_only_if_verified(live_settings, scratch_unit):
    factory = get_session_factory(live_settings)
    email = f"test-sso-local-{scratch_unit}@example.com"
    async with factory() as session:
        await UserRepository(session).create(name="Local", email=email, password_hash=hash_password("x"), role="admin", tenant=scratch_unit)
        await session.commit()
    claims = {"iss": ISSUER, "sub": uuid.uuid4().hex, "email": email, "groups": []}
    try:
        async with factory() as session:
            with pytest.raises(SignInFailed):
                await sign_in(live_settings, session, {**claims, "email_verified": False})
            await session.rollback()
            joined = await sign_in(live_settings, session, {**claims, "email_verified": True})
            await session.commit()
            assert joined.subject == f"{ISSUER} {claims['sub']}"
            assert await _memberships(session, joined.id) == {scratch_unit: ("admin", "local")}  # kept: Veritium manages it
            with pytest.raises(SignInFailed):  # another provider identity with the same e-mail is someone else
                await sign_in(live_settings, session, {**claims, "sub": uuid.uuid4().hex, "email_verified": True})
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()
