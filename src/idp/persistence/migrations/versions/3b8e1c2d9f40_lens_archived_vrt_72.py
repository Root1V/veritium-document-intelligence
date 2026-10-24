"""lens archived vrt 72

A lens is archived, not deleted: the starting ones would come back at the
next start, and its readings keep the definition they were made with.

Revision ID: 3b8e1c2d9f40
Revises: 07182f1dd2a0
Create Date: 2026-10-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b8e1c2d9f40'
down_revision: Union[str, Sequence[str], None] = '07182f1dd2a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('lenses', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('lenses', 'archived_at')
