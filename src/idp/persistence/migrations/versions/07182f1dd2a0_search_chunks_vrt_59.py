"""search chunks vrt 59

Hybrid search: the searchable pieces of each document, with a Spanish
full-text vector that ignores accents, a trigram index for misspellings,
and a halfvec embedding. Existing documents are indexed by
scripts/reindex_search.py, not here.

Revision ID: 07182f1dd2a0
Revises: 12fb7f00cd9c
Create Date: 2026-10-24 08:10:12.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '07182f1dd2a0'
down_revision: Union[str, Sequence[str], None] = '12fb7f00cd9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    # Spanish stemming over unaccented words: «Pérez» and «perez», «préstamos» and «prestamo» meet.
    # A configuration, not unaccent() in the expression: the generated column needs an immutable one.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'es_sin_tildes') THEN
                CREATE TEXT SEARCH CONFIGURATION es_sin_tildes (COPY = spanish);
                ALTER TEXT SEARCH CONFIGURATION es_sin_tildes
                    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;
            END IF;
        END $$
    """)
    op.create_table(
        'search_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('es_sin_tildes'::regconfig, content)", persisted=True), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.HALFVEC(dim=1024), nullable=True),
        sa.Column('embedding_model', sa.String(length=128), nullable=True),
        sa.Column('tenant', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant'], ['tenants.key']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_search_chunks_case_id'), 'search_chunks', ['case_id'], unique=False)
    op.create_index(op.f('ix_search_chunks_document_id'), 'search_chunks', ['document_id'], unique=False)
    op.create_index('ix_search_chunks_tsv', 'search_chunks', ['tsv'], unique=False, postgresql_using='gin')
    op.create_index('ix_search_chunks_trgm', 'search_chunks', ['content'], unique=False, postgresql_using='gin', postgresql_ops={'content': 'gin_trgm_ops'})
    op.create_index('ix_search_chunks_embedding', 'search_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'halfvec_cosine_ops'})


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('search_chunks')
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS es_sin_tildes")
