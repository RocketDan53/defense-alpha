"""Add parent_event_id to funding_events

Revision ID: 351c28b78ecd
Revises: b715356d1f4f
Create Date: 2026-02-26 15:53:21.242633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '351c28b78ecd'
down_revision: Union[str, Sequence[str], None] = 'b715356d1f4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('funding_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_event_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key('fk_funding_parent', 'funding_events', ['parent_event_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('funding_events', schema=None) as batch_op:
        batch_op.drop_constraint('fk_funding_parent', type_='foreignkey')
        batch_op.drop_column('parent_event_id')
