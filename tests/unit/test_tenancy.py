"""Every table is either one business unit's or corporate, on purpose
(VRT-57): a new table has to be put on one side, or this fails."""

from __future__ import annotations

from idp.persistence.models import Base
from idp.persistence.tenancy import TenantScoped

# Shared by every unit: the people, the units, and the corporate catalogs.
CORPORATE = {
    "users", "tenants", "memberships", "document_types", "document_type_versions", "semantic_catalog_versions",
    "validation_rule_definitions", "lenses", "prompt_versions", "prompt_edits",
}


def test_every_table_is_a_units_or_corporate():
    tables = {m.class_.__tablename__: issubclass(m.class_, TenantScoped) for m in Base.registry.mappers}
    unclassified = {t for t, scoped in tables.items() if not scoped and t not in CORPORATE}
    assert not unclassified, f"tablas sin clasificar (¿de una unidad o corporativas?): {sorted(unclassified)}"
    assert not {t for t, scoped in tables.items() if scoped and t in CORPORATE}


def test_a_units_row_cannot_exist_without_its_unit():
    for mapper in Base.registry.mappers:
        if issubclass(mapper.class_, TenantScoped):
            column = mapper.local_table.c.tenant
            assert not column.nullable and column.default is None and column.server_default is None, mapper.class_.__name__
