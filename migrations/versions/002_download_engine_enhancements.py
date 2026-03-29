"""Add alt-platform support and per-channel subtitle/metadata/thumbnail settings.

Implements:
  - Issue #16: Bitchute and Odysee platform support (no schema change needed,
    platform column already stores arbitrary strings; comment updated)
  - Issue #17: download_subtitles, subtitle_langs, embed_metadata columns
  - Issue #21: save_thumbnail column

Revision ID: 002
Revises: 001
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite requires batch mode for ALTER TABLE operations.
    with op.batch_alter_table('channels') as batch_op:
        batch_op.add_column(
            sa.Column('download_subtitles', sa.Boolean(), nullable=True, server_default='0')
        )
        batch_op.add_column(
            sa.Column('subtitle_langs', sa.String(length=255), nullable=True, server_default='en')
        )
        batch_op.add_column(
            sa.Column('embed_metadata', sa.Boolean(), nullable=True, server_default='0')
        )
        batch_op.add_column(
            sa.Column('save_thumbnail', sa.Boolean(), nullable=True, server_default='0')
        )


def downgrade():
    with op.batch_alter_table('channels') as batch_op:
        batch_op.drop_column('save_thumbnail')
        batch_op.drop_column('embed_metadata')
        batch_op.drop_column('subtitle_langs')
        batch_op.drop_column('download_subtitles')
