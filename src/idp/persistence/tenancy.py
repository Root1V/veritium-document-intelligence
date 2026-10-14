"""Which business unit (tenant) a unit of work acts for, and the one seam
that keeps every query inside it (VRT-57).

The tenant is set once per unit of work, never read from a request: from
the caller's credential (auth/authenticate.py), from the case a worker step
runs for, or explicitly ``system()`` for the few jobs that span every unit
(the webhook dispatcher, the bulk scheduler). Then, for every model that
mixes in ``TenantScoped``:

- every ORM SELECT, UPDATE and DELETE gets ``tenant = <current>`` added, so
  another unit's row is indistinguishable from one that does not exist —
  a 404, never a 403;
- every new row is stamped with the current tenant, and a row of another
  tenant cannot be written;
- with no tenant set, a statement on such a model fails instead of reading
  everything (fail closed).

Filtering here, and not route by route, is the point: a route cannot forget
a predicate it never writes. A Core ``insert()`` bypasses the stamping, so
it names the tenant itself — the column has no default, so forgetting fails.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import ForeignKey, String, event
from sqlalchemy.orm import Mapped, ORMExecuteState, Session, mapped_column, with_loader_criteria
from sqlalchemy.sql.util import find_tables

SYSTEM = "*"
_TENANT_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_current: ContextVar[str | None] = ContextVar("veritium_tenant", default=None)


class TenantNotSet(RuntimeError):
    """A tenant-scoped statement ran with no tenant: a bug, never a fallback."""


class CrossTenantWrite(RuntimeError):
    pass


def valid_key(key: str) -> bool:
    return bool(_TENANT_KEY.match(key))


def use(tenant: str) -> None:
    """Acts for ``tenant`` for the rest of this task (and the tasks it starts)."""
    if not valid_key(tenant):
        raise ValueError(f"unidad inválida: {tenant!r}")
    _current.set(tenant)


@contextmanager
def acting_for(tenant: str) -> Iterator[None]:
    if not valid_key(tenant):
        raise ValueError(f"unidad inválida: {tenant!r}")
    token = _current.set(tenant)
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def system() -> Iterator[None]:
    """Reads across every unit. Only for jobs that are not any unit's — each use says why."""
    token = _current.set(SYSTEM)
    try:
        yield
    finally:
        _current.reset(token)


def active() -> str | None:
    """The unit this work acts for, or None when there is none (or under ``system()``)."""
    tenant = _current.get()
    return None if tenant == SYSTEM else tenant


def current() -> str:
    """The unit this work acts for; raises when there is none (or under ``system()``)."""
    tenant = _current.get()
    if tenant is None or tenant == SYSTEM:
        raise TenantNotSet("no hay una unidad de negocio activa")
    return tenant


class TenantScoped:
    """Mixin: rows that belong to one business unit."""

    tenant: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.key"), nullable=False)


def _scoped_classes() -> list[type]:
    return [m.class_ for m in _registry() if issubclass(m.class_, TenantScoped)]


def _registry():
    from idp.persistence.models import Base

    return Base.registry.mappers


@event.listens_for(Session, "do_orm_execute")
def _within_tenant(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete) or state.is_column_load or state.is_relationship_load:
        return
    tenant = _current.get()
    if tenant == SYSTEM:
        return
    if tenant is None:
        scoped = {cls.__table__ for cls in _scoped_classes()}
        if any(t in scoped for t in find_tables(state.statement, include_aliases=True, include_joins=True, check_columns=True)):
            raise TenantNotSet("consulta sobre datos de una unidad sin unidad activa")
        return
    state.statement = state.statement.options(
        *(with_loader_criteria(cls, lambda c: c.tenant == tenant, include_aliases=True, track_closure_variables=True) for cls in _scoped_classes())
    )


@event.listens_for(Session, "before_flush")
def _stamp(session: Session, flush_context, instances) -> None:  # noqa: ANN001 — SQLAlchemy's signature
    tenant = _current.get()
    for obj in session.new:
        if not isinstance(obj, TenantScoped):
            continue
        if obj.tenant is None:
            if tenant is None or tenant == SYSTEM:
                raise TenantNotSet(f"{type(obj).__name__} nuevo sin unidad activa")
            obj.tenant = tenant
        elif tenant is None:
            raise TenantNotSet(f"{type(obj).__name__} nuevo sin unidad activa")
        elif tenant != SYSTEM and obj.tenant != tenant:
            raise CrossTenantWrite(f"{type(obj).__name__} de otra unidad")
    if tenant is None or tenant == SYSTEM:
        return
    for obj in session.dirty:
        if isinstance(obj, TenantScoped) and obj.tenant != tenant:
            raise CrossTenantWrite(f"{type(obj).__name__} de otra unidad")
