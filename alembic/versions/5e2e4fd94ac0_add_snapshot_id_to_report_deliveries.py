"""Add snapshot_id to report_deliveries

Revision ID: 5e2e4fd94ac0
Revises: eb5aadea1862
Create Date: 2026-02-26 11:28:53.987897

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e2e4fd94ac0'
down_revision: Union[str, Sequence[str], None] = 'eb5aadea1862'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('report_deliveries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('snapshot_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key('fk_delivery_snapshot', 'entity_snapshots', ['snapshot_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('report_deliveries', schema=None) as batch_op:
        batch_op.drop_constraint('fk_delivery_snapshot', type_='foreignkey')
        batch_op.drop_column('snapshot_id')
