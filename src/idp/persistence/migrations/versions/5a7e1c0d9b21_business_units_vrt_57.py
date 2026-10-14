"""business units vrt 57

Every unit-owned row gets its unit; what exists today becomes the unit
``default``. A person's role moves from ``users.role`` to one membership per
unit. Keys that were unique platform-wide become unique per unit.

Revision ID: 5a7e1c0d9b21
Revises: c3b77fbbb653
Create Date: 2026-10-14 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5a7e1c0d9b21'
down_revision: Union[str, Sequence[str], None] = 'c3b77fbbb653'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that already had the placeholder column (always "default").
_HAD_TENANT = ("cases", "outbox_events", "webhook_endpoints", "bulk_jobs")
_NEW_TENANT = (
    "case_runs", "documents", "extractions", "validation_issues", "review_items", "audit_log", "document_type_suggestions",
    "reference_employees", "process_profiles", "process_profile_versions", "case_conditions", "webhook_deliveries",
    "eval_suites", "eval_cases", "eval_runs", "eval_results", "calibration_versions", "simulations", "simulation_results",
    "lens_results", "api_clients", "investigations", "a2a_tasks", "upload_sessions", "uploaded_files",
)


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.execute("INSERT INTO tenants (key, name) VALUES ('default', 'Unidad principal')")

    op.create_table(
        'memberships',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('tenant', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=8), server_default='local', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant'], ['tenants.key']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'tenant'),
    )
    op.execute("INSERT INTO memberships (id, user_id, tenant, role) SELECT gen_random_uuid(), id, 'default', role FROM users")
    op.drop_column('users', 'role')
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=256), nullable=True)
    op.add_column('users', sa.Column('subject', sa.String(length=512), nullable=True))
    op.create_unique_constraint('users_subject_key', 'users', ['subject'])

    for table in _NEW_TENANT:
        op.add_column(table, sa.Column('tenant', sa.String(length=64), server_default='default', nullable=False))
        op.alter_column(table, 'tenant', server_default=None)
    for table in _HAD_TENANT + _NEW_TENANT:
        op.create_foreign_key(f'{table}_tenant_fkey', table, 'tenants', ['tenant'], ['key'])

    op.drop_constraint('process_profiles_key_key', 'process_profiles', type_='unique')
    op.create_unique_constraint('process_profiles_tenant_key_key', 'process_profiles', ['tenant', 'key'])
    op.drop_constraint('reference_employees_employee_code_key', 'reference_employees', type_='unique')
    op.create_unique_constraint('reference_employees_tenant_employee_code_key', 'reference_employees', ['tenant', 'employee_code'])
    op.drop_constraint('calibration_versions_version_key', 'calibration_versions', type_='unique')
    op.create_unique_constraint('calibration_versions_tenant_version_key', 'calibration_versions', ['tenant', 'version'])
    op.drop_index('ix_calibration_one_active', table_name='calibration_versions')
    op.create_index('ix_calibration_one_active', 'calibration_versions', ['tenant'], unique=True, postgresql_where=sa.text("status = 'active'"))


def downgrade() -> None:
    """Only back from a single unit: rows of other units would collide."""
    op.drop_index('ix_calibration_one_active', table_name='calibration_versions')
    op.create_index('ix_calibration_one_active', 'calibration_versions', ['status'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.drop_constraint('calibration_versions_tenant_version_key', 'calibration_versions', type_='unique')
    op.create_unique_constraint('calibration_versions_version_key', 'calibration_versions', ['version'])
    op.drop_constraint('reference_employees_tenant_employee_code_key', 'reference_employees', type_='unique')
    op.create_unique_constraint('reference_employees_employee_code_key', 'reference_employees', ['employee_code'])
    op.drop_constraint('process_profiles_tenant_key_key', 'process_profiles', type_='unique')
    op.create_unique_constraint('process_profiles_key_key', 'process_profiles', ['key'])
    for table in _HAD_TENANT + _NEW_TENANT:
        op.drop_constraint(f'{table}_tenant_fkey', table, type_='foreignkey')
    for table in _NEW_TENANT:
        op.drop_column(table, 'tenant')
    op.drop_constraint('users_subject_key', 'users', type_='unique')
    op.drop_column('users', 'subject')
    op.add_column('users', sa.Column('role', sa.String(length=16), server_default='operador', nullable=False))
    op.execute("UPDATE users u SET role = m.role FROM memberships m WHERE m.user_id = u.id AND m.tenant = 'default'")
    op.drop_table('memberships')
    op.drop_table('tenants')
