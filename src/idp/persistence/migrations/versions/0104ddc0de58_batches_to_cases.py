"""batches -> cases (VRT-25): rename the aggregate, add case runs, profile
pinning, idempotency, verdict columns and superseded validation issues.

Hand-written: autogenerate would read the rename as drop + create and lose
every existing case. Ids are preserved, so object-store keys (which embed
the old batch id) stay valid.

Revision ID: 0104ddc0de58
Revises: 0ad8f2e14690
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0104ddc0de58"
down_revision: Union[str, Sequence[str], None] = "0ad8f2e14690"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("batches", "cases")
    for table in ("documents", "validation_issues", "document_type_suggestions"):
        op.alter_column(table, "batch_id", new_column_name="case_id")

    op.add_column("cases", sa.Column("profile_version_id", sa.UUID(), nullable=True))
    op.add_column("cases", sa.Column("external_ref", sa.String(length=256), nullable=True))
    op.add_column("cases", sa.Column("channel", sa.String(length=16), server_default="backoffice", nullable=False))
    op.add_column("cases", sa.Column("idempotency_key", sa.String(length=256), nullable=True))
    op.add_column("cases", sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("cases", sa.Column("verdict", sa.String(length=32), nullable=True))
    op.add_column("cases", sa.Column("verdict_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("cases", sa.Column("verdict_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("cases_profile_version_id_fkey", "cases", "process_profile_versions", ["profile_version_id"], ["id"])
    op.create_unique_constraint("uq_cases_tenant_idempotency_key", "cases", ["tenant", "idempotency_key"])

    op.create_table(
        "case_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("profile_version_id", sa.UUID(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("execution_ref", sa.String(length=256), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_version_id"], ["process_profile_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "run_number"),
    )

    op.add_column("validation_issues", sa.Column("case_run_id", sa.UUID(), nullable=True))
    op.add_column("validation_issues", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("validation_issues_case_run_id_fkey", "validation_issues", "case_runs", ["case_run_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("validation_issues_case_run_id_fkey", "validation_issues", type_="foreignkey")
    op.drop_column("validation_issues", "superseded_at")
    op.drop_column("validation_issues", "case_run_id")
    op.drop_table("case_runs")
    op.drop_constraint("uq_cases_tenant_idempotency_key", "cases", type_="unique")
    op.drop_constraint("cases_profile_version_id_fkey", "cases", type_="foreignkey")
    for column in ("verdict_at", "verdict_reasons", "verdict", "idempotency_fingerprint", "idempotency_key", "channel", "external_ref", "profile_version_id"):
        op.drop_column("cases", column)
    for table in ("documents", "validation_issues", "document_type_suggestions"):
        op.alter_column(table, "case_id", new_column_name="batch_id")
    op.rename_table("cases", "batches")
