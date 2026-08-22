"""notes-first rework: checklist_items, notes.lesson_id, drop lesson_items

Revision ID: 06e630770a79
Revises: 17da8cdf5990
Create Date: 2026-08-22 19:47:16.684436
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '06e630770a79'
down_revision = '17da8cdf5990'
branch_labels = None
depends_on = None




def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return bind.execute(sa.text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :n"
    ), {"n": name}).fetchone() is not None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f'PRAGMA table_info("{table}")')).fetchall()
    return any(r[1] == column for r in rows)


def _convert_lesson_items() -> None:
    """Consolidated addendum §2 — "convert each into a `checklist_item` block
    appended to that lesson's note (creating the note first if needed)".

    A no-op on a database where §0's reset already ran, or where the tree
    builder was never used. Written anyway: dropping a table the user might
    have typed into without moving the content first would be data loss.
    """
    import hashlib
    from datetime import date, datetime, timezone

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, lesson_id, title, done, position FROM lesson_items "
        "WHERE deleted_at IS NULL ORDER BY lesson_id, position, id"
    )).fetchall()
    if not rows:
        return

    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()
    converted = 0

    for _item_id, lesson_id, title, done, position in rows:
        lesson = bind.execute(sa.text(
            "SELECT name, topic_id, subtopic_id FROM lessons WHERE id = :id"
        ), {"id": lesson_id}).fetchone()
        if lesson is None:
            continue
        name, topic_id, subtopic_id = lesson

        note = bind.execute(sa.text(
            "SELECT id FROM notes WHERE lesson_id = :lid AND deleted_at IS NULL "
            "ORDER BY id LIMIT 1"
        ), {"lid": lesson_id}).fetchone()

        if note is None:
            subject_id = None
            if topic_id is not None:
                subject = bind.execute(sa.text(
                    "SELECT subject_id FROM topics WHERE id = :id"
                ), {"id": topic_id}).fetchone()
                subject_id = subject[0] if subject else None
            bind.execute(sa.text(
                "INSERT INTO notes (title, study_date, subject_id, topic_id, "
                "subtopic_id, lesson_id, created_at, updated_at) VALUES "
                "(:title, :d, :sub, :top, :st, :lid, :now, :now)"
            ), {"title": name, "d": today, "sub": subject_id, "top": topic_id,
                "st": subtopic_id, "lid": lesson_id, "now": now})
            note_id = bind.execute(sa.text("SELECT last_insert_rowid()")).scalar()
        else:
            note_id = note[0]

        next_position = bind.execute(sa.text(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM note_blocks "
            "WHERE note_id = :nid"
        ), {"nid": note_id}).scalar()

        text = f"- [{'x' if done else ' '}] {title}"
        digest = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
        bind.execute(sa.text(
            "INSERT INTO note_blocks (note_id, position, block_type, text, "
            "checked, content_hash, created_at, updated_at) VALUES "
            "(:nid, :pos, 'checklist_item', :text, :checked, :hash, :now, :now)"
        ), {"nid": note_id, "pos": next_position, "text": text,
            "checked": 1 if done else 0, "hash": digest, "now": now})
        block_id = bind.execute(sa.text("SELECT last_insert_rowid()")).scalar()

        # The projection is normally rebuilt whenever a note is saved, but a
        # converted item would then stay invisible in the Roadmap and the
        # right panel until the user happened to edit that note. So the row is
        # written here too, exactly as `checklist.reconcile_note` would write
        # it: the parsed body, not the `- [ ]` syntax.
        bind.execute(sa.text(
            "INSERT INTO checklist_items (note_block_id, note_id, lesson_id, "
            "text, checked, completed_at, position, created_at, updated_at) "
            "VALUES (:bid, :nid, :lid, :text, :checked, :done_at, :pos, "
            ":now, :now)"
        ), {"bid": block_id, "nid": note_id, "lid": lesson_id, "text": title,
            "checked": 1 if done else 0, "done_at": now if done else None,
            "pos": next_position, "now": now})
        converted += 1

    print(f"  converted {converted} lesson_item(s) into checklist_item blocks")


def upgrade() -> None:
    # Order matters, and it is the opposite of what autogenerate produced:
    # `_convert_lesson_items` writes `notes.lesson_id` and
    # `note_blocks.checked`, so those columns have to exist before it runs,
    # and `lesson_items` can only be dropped after. Converting first looked
    # right — and passed every test — only because an empty database has no
    # items to convert, so the function returned before touching a column
    # that was not there yet.
    #
    # Every step is guarded, because this revision has already been applied
    # halfway to a real database: pysqlite opens no transaction for DDL, so an
    # interrupted run committed what had already succeeded while
    # `alembic_version` stayed put. migrations/env.py now forces transactional
    # DDL so it cannot happen again, but the databases it happened to still
    # have to reach head. On a clean database the guards change nothing.

    if not _has_column('note_blocks', 'checked'):
        with op.batch_alter_table('note_blocks', schema=None) as batch_op:
            # server_default, because the table already has rows: a NOT NULL
            # column with no default fails the moment one exists.
            batch_op.add_column(sa.Column('checked', sa.Boolean(), nullable=False,
                                          server_default=sa.text('0')))
            batch_op.add_column(sa.Column('url', sqlmodel.sql.sqltypes.AutoString(),
                                          nullable=True))
            batch_op.add_column(sa.Column('parent_block_id', sa.Integer(), nullable=True))
            # Named explicitly: SQLite's batch ALTER rebuilds the table and
            # cannot add an anonymous constraint.
            batch_op.create_foreign_key(
                'fk_note_blocks_parent_block_id', 'note_blocks',
                ['parent_block_id'], ['id'],
            )

    if not _has_column('notes', 'lesson_id'):
        with op.batch_alter_table('notes', schema=None) as batch_op:
            batch_op.add_column(sa.Column('lesson_id', sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f('ix_notes_lesson_id'), ['lesson_id'],
                                  unique=False)
            batch_op.create_foreign_key(
                'fk_notes_lesson_id', 'lessons', ['lesson_id'], ['id'],
            )

    if not _has_table('checklist_items'):
        op.create_table(
            'checklist_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('note_block_id', sa.Integer(), nullable=False),
            sa.Column('note_id', sa.Integer(), nullable=False),
            sa.Column('lesson_id', sa.Integer(), nullable=True),
            sa.Column('parent_checklist_item_id', sa.Integer(), nullable=True),
            sa.Column('text', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column('checked', sa.Boolean(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ),
            sa.ForeignKeyConstraint(['note_block_id'], ['note_blocks.id'], ),
            sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ),
            sa.ForeignKeyConstraint(['parent_checklist_item_id'],
                                    ['checklist_items.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('note_block_id', name='uq_checklist_note_block'),
        )
        with op.batch_alter_table('checklist_items', schema=None) as batch_op:
            batch_op.create_index('ix_checklist_items_lesson', ['lesson_id'],
                                  unique=False)
            batch_op.create_index('ix_checklist_items_note', ['note_id'],
                                  unique=False)

    # The lesson_items index disappears with its table; dropping it separately
    # makes the downgrade fail, because the recreated table has none yet.
    if _has_table('lesson_items'):
        _convert_lesson_items()
        op.drop_table('lesson_items')


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_notes_lesson_id'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_notes_lesson_id'))
        batch_op.drop_column('lesson_id')

    with op.batch_alter_table('note_blocks', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_note_blocks_parent_block_id'), type_='foreignkey')
        batch_op.drop_column('parent_block_id')
        batch_op.drop_column('url')
        batch_op.drop_column('checked')

    op.create_table('lesson_items',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('lesson_id', sa.INTEGER(), nullable=False),
    sa.Column('title', sa.VARCHAR(), nullable=False),
    sa.Column('position', sa.INTEGER(), nullable=False),
    sa.Column('done', sa.BOOLEAN(), nullable=False),
    sa.Column('completed_at', sa.DATETIME(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), nullable=False),
    sa.Column('deleted_at', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('checklist_items', schema=None) as batch_op:
        batch_op.drop_index('ix_checklist_items_note')
        batch_op.drop_index('ix_checklist_items_lesson')

    # Restore the index too: revision 17da8cdf5990's own downgrade drops it
    # by name, so leaving it off breaks the chain one step further down.
    with op.batch_alter_table('lesson_items', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_lesson_items_lesson_position'),
            ['lesson_id', 'position'], unique=False,
        )

    op.drop_table('checklist_items')
    # ### end Alembic commands ###
