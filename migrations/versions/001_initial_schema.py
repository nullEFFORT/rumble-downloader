"""Initial schema with audio_only and clip_start/clip_end columns.

Revision ID: 001
Revises:
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create channels table
    op.create_table('channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False),
        sa.Column('channel_id', sa.String(length=255), nullable=True),
        sa.Column('rss_url', sa.String(length=512), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True, default=True),
        sa.Column('download_clips', sa.Boolean(), nullable=True, default=False),
        sa.Column('clip_threshold_seconds', sa.Integer(), nullable=True, default=300),
        sa.Column('backfill_enabled', sa.Boolean(), nullable=True, default=False),
        sa.Column('backfill_limit', sa.Integer(), nullable=True, default=50),
        sa.Column('quality', sa.String(length=50), nullable=True, default='1080'),
        sa.Column('audio_only', sa.Boolean(), nullable=True, default=False),
        sa.Column('check_interval_hours', sa.Integer(), nullable=True, default=6),
        sa.Column('last_checked', sa.DateTime(), nullable=True),
        sa.Column('video_count', sa.Integer(), nullable=True, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url'),
    )

    # Create videos table
    op.create_table('videos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_id', sa.String(length=255), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=True),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('upload_date', sa.Date(), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=512), nullable=True),
        sa.Column('is_clip', sa.Boolean(), nullable=True, default=False),
        sa.Column('classification_reason', sa.String(length=255), nullable=True),
        sa.Column('clip_start', sa.String(length=20), nullable=True),
        sa.Column('clip_end', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, default='pending'),
        sa.Column('priority', sa.Integer(), nullable=True, default=0),
        sa.Column('downloaded_at', sa.DateTime(), nullable=True),
        sa.Column('file_path', sa.String(length=1024), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('discovered_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('video_id', 'channel_id', name='unique_video_per_channel'),
    )

    # Create download_logs table
    op.create_table('download_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_id', sa.Integer(), nullable=True),
        sa.Column('channel_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id']),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('download_logs')
    op.drop_table('videos')
    op.drop_table('channels')
