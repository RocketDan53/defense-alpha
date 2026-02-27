"""Add enrichment_findings table

Revision ID: b715356d1f4f
Revises: 5e2e4fd94ac0
Create Date: 2026-02-26 12:23:43.355997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'b715356d1f4f'
down_revision: Union[str, Sequence[str], None] = '5e2e4fd94ac0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('enrichment_findings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('finding_type', sa.String(length=50), nullable=False),
    sa.Column('finding_data', sqlite.JSON(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('confidence', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_by', sa.String(length=50), nullable=True),
    sa.Column('ingested_at', sa.DateTime(), nullable=True),
    sa.Column('ingested_record_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('enrichment_findings', schema=None) as batch_op:
        batch_op.create_index('ix_enrichment_entity_status', ['entity_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_enrichment_findings_entity_id'), ['entity_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('enrichment_findings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_enrichment_findings_entity_id'))
        batch_op.drop_index('ix_enrichment_entity_status')

    op.drop_table('enrichment_findings')
