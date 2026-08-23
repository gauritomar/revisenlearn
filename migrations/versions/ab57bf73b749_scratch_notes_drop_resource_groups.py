"""scratch notes; drop resource groups

Revision ID: ab57bf73b749
Revises: feb536c4ee1b
Create Date: 2026-08-23 15:56:36.126552
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'ab57bf73b749'
down_revision = 'feb536c4ee1b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A scratch page: somewhere to write that is not study material. One per
    # key, hanging off nothing in the tree.
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scratch_key', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_notes_scratch_key'), ['scratch_key'], unique=False)

    # The resource-heading scaffolding goes with the screen it was built for.
    # `tags` and `taggings` stay: they are spec §6 tables, they predate this,
    # and they hold the user's own labels.
    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.drop_constraint('fk_resources_group_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_resources_group_id'))
        batch_op.drop_column('group_id')

    with op.batch_alter_table('resource_groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_resource_groups_name'))
    op.drop_table('resource_groups')


def downgrade() -> None:
    op.create_table(
        'resource_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('colour', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('resource_groups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_resource_groups_name'), ['name'],
                              unique=False)

    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_resources_group_id'), ['group_id'],
                              unique=False)
        batch_op.create_foreign_key(
            'fk_resources_group_id', 'resource_groups', ['group_id'], ['id'])

    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notes_scratch_key'))
        batch_op.drop_column('scratch_key')

    # ### end Alembic commands ###
