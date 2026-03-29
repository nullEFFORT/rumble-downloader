"""Database models for channel and video tracking."""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Channel(db.Model):
    """Tracked channel (YouTube or Rumble)."""

    __tablename__ = 'channels'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(512), nullable=False, unique=True)
    platform = db.Column(db.String(50), nullable=False)  # 'youtube', 'rumble', 'bitchute', 'odysee'
    channel_id = db.Column(db.String(255))  # YouTube channel ID for RSS
    rss_url = db.Column(db.String(512))  # YouTube RSS feed URL

    # Settings
    enabled = db.Column(db.Boolean, default=True)
    download_clips = db.Column(db.Boolean, default=False)  # Include short clips
    clip_threshold_seconds = db.Column(db.Integer, default=300)  # 5 min default
    backfill_enabled = db.Column(db.Boolean, default=False)
    backfill_limit = db.Column(db.Integer, default=50)  # Max videos to backfill
    quality = db.Column(db.String(50), default='1080')  # Max resolution

    # Download mode
    audio_only = db.Column(db.Boolean, default=False)  # Download audio only (mp3)

    # Subtitle settings (issue #17)
    download_subtitles = db.Column(db.Boolean, default=False)
    subtitle_langs = db.Column(db.String(255), default='en')  # Comma-separated, e.g. "en,es"

    # Metadata / thumbnail embedding (issues #17, #21)
    embed_metadata = db.Column(db.Boolean, default=False)
    save_thumbnail = db.Column(db.Boolean, default=False)

    # Schedule (cron-like)
    check_interval_hours = db.Column(db.Integer, default=6)

    # Metadata
    last_checked = db.Column(db.DateTime)
    video_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    videos = db.relationship('Video', backref='channel', lazy='dynamic',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Channel {self.name} ({self.platform})>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'platform': self.platform,
            'channel_id': self.channel_id,
            'enabled': self.enabled,
            'download_clips': self.download_clips,
            'clip_threshold_seconds': self.clip_threshold_seconds,
            'backfill_enabled': self.backfill_enabled,
            'backfill_limit': self.backfill_limit,
            'quality': self.quality,
            'audio_only': self.audio_only,
            'download_subtitles': self.download_subtitles,
            'subtitle_langs': self.subtitle_langs,
            'embed_metadata': self.embed_metadata,
            'save_thumbnail': self.save_thumbnail,
            'check_interval_hours': self.check_interval_hours,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'video_count': self.video_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Video(db.Model):
    """Tracked video (downloaded or pending)."""

    __tablename__ = 'videos'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.String(255), nullable=False)  # Platform video ID
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'), nullable=False)

    # Metadata
    title = db.Column(db.String(512))
    url = db.Column(db.String(512), nullable=False)
    duration = db.Column(db.Integer)  # Seconds
    upload_date = db.Column(db.Date)
    thumbnail_url = db.Column(db.String(512))

    # Classification
    is_clip = db.Column(db.Boolean, default=False)
    classification_reason = db.Column(db.String(255))  # Why it was classified as clip

    # Timestamp clipping
    clip_start = db.Column(db.String(20))  # HH:MM:SS or seconds
    clip_end = db.Column(db.String(20))    # HH:MM:SS or seconds

    # Download status
    status = db.Column(db.String(50), default='pending')  # pending, downloading, completed, failed, skipped
    priority = db.Column(db.Integer, default=0)  # Higher = download first
    downloaded_at = db.Column(db.DateTime)
    file_path = db.Column(db.String(1024))
    file_size = db.Column(db.BigInteger)  # Bytes
    error_message = db.Column(db.Text)

    # Timestamps
    discovered_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('video_id', 'channel_id', name='unique_video_per_channel'),
    )

    def __repr__(self):
        return f'<Video {self.title[:30] if self.title else self.video_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'video_id': self.video_id,
            'channel_id': self.channel_id,
            'title': self.title,
            'url': self.url,
            'duration': self.duration,
            'duration_formatted': self._format_duration(),
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'thumbnail_url': self.thumbnail_url,
            'is_clip': self.is_clip,
            'classification_reason': self.classification_reason,
            'clip_start': self.clip_start,
            'clip_end': self.clip_end,
            'status': self.status,
            'priority': self.priority,
            'downloaded_at': self.downloaded_at.isoformat() if self.downloaded_at else None,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'file_size_formatted': self._format_size(),
            'error_message': self.error_message,
            'discovered_at': self.discovered_at.isoformat() if self.discovered_at else None,
        }

    def _format_duration(self):
        if not self.duration:
            return None
        hours, remainder = divmod(self.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f'{hours}:{minutes:02d}:{seconds:02d}'
        return f'{minutes}:{seconds:02d}'

    def _format_size(self):
        if not self.file_size:
            return None
        for unit in ['B', 'KB', 'MB', 'GB']:
            if self.file_size < 1024:
                return f'{self.file_size:.1f} {unit}'
            self.file_size /= 1024
        return f'{self.file_size:.1f} TB'


class DownloadLog(db.Model):
    """Log of download activities."""

    __tablename__ = 'download_logs'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'))
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'))

    action = db.Column(db.String(50))  # check, download, skip, error
    message = db.Column(db.Text)
    details = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DownloadLog {self.action} at {self.created_at}>'
