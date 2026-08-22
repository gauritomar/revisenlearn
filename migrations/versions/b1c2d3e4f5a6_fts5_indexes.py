"""FTS5 virtual tables for note blocks and concepts

Spec §6: "FTS5: virtual table over note_blocks.text and
concepts.canonical_name || definition."

These are standalone (not external-content) FTS5 tables. The application keeps
them in step on every block write via ``db.reindex_block``; a contentless
external-content table would need triggers that fight with soft-delete
semantics, and at single-user scale the duplicated text costs nothing.

Revision ID: b1c2d3e4f5a6
Revises: 6a9a48c36ece
"""
from __future__ import annotations

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "6a9a48c36ece"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS note_blocks_fts USING fts5(
            text,
            note_id UNINDEXED,
            note_block_id UNINDEXED,
            tokenize = 'porter unicode61'
        )
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
            canonical_name,
            definition,
            concept_id UNINDEXED,
            tokenize = 'porter unicode61'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS concepts_fts")
    op.execute("DROP TABLE IF EXISTS note_blocks_fts")
