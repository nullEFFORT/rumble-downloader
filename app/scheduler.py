"""Background scheduler for channel checking and video downloading."""

import logging
from datetime import datetime, timedelta
from threading import Thread

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import feedparser

from .models import db, Channel, Video, DownloadLog
from .downloader import VideoDownloader

logger = logging.getLogger(__name__)


class DownloadScheduler:
    """Manages scheduled channel checks and downloads."""

    def __init__(self, app=None, download_path: str = '/downloads'):
        self.scheduler = BackgroundScheduler()
        self.downloader = VideoDownloader(download_path)
        self.app = app
        self.download_path = download_path
        self._is_running = False

    def init_app(self, app):
        """Initialize with Flask app."""
        self.app = app
        self.download_path = app.config.get('DOWNLOAD_PATH', '/downloads')
        self.downloader = VideoDownloader(self.download_path)

    def start(self):
        """Start the scheduler."""
        if self._is_running:
            return

        # Add job to check all channels periodically
        self.scheduler.add_job(
            self._check_all_channels,
            IntervalTrigger(hours=1),
            id='check_channels',
            name='Check all channels for new videos',
            replace_existing=True,
        )

        # Add job to process download queue
        self.scheduler.add_job(
            self._process_download_queue,
            IntervalTrigger(minutes=5),
            id='process_downloads',
            name='Process pending downloads',
            replace_existing=True,
        )

        self.scheduler.start()
        self._is_running = True
        logger.info('Download scheduler started')

    def stop(self):
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info('Download scheduler stopped')

    def _check_all_channels(self):
        """Check all enabled channels for new videos."""
        with self.app.app_context():
            channels = Channel.query.filter_by(enabled=True).all()

            for channel in channels:
                # Check if it's time to check this channel
                if channel.last_checked:
                    next_check = channel.last_checked + timedelta(hours=channel.check_interval_hours)
                    if datetime.utcnow() < next_check:
                        continue

                logger.info(f'Checking channel: {channel.name}')
                self._check_channel(channel)

    def _check_channel(self, channel: Channel):
        """Check a single channel for new videos."""
        try:
            new_videos = []

            if channel.platform == 'youtube' and channel.rss_url:
                # Use RSS for YouTube (faster)
                new_videos = self._check_youtube_rss(channel)
            else:
                # Fall back to yt-dlp for Rumble or YouTube without RSS
                new_videos = self._check_via_ytdlp(channel)

            # Log the check
            self._log_action(channel.id, None, 'check',
                           f'Found {len(new_videos)} new videos',
                           {'video_count': len(new_videos)})

            channel.last_checked = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            logger.error(f'Error checking channel {channel.name}: {e}')
            self._log_action(channel.id, None, 'error',
                           f'Error checking channel: {e}')

    def _check_youtube_rss(self, channel: Channel) -> list:
        """Check YouTube RSS feed for new videos."""
        feed = feedparser.parse(channel.rss_url)
        new_videos = []

        for entry in feed.entries:
            video_id = entry.yt_videoid if hasattr(entry, 'yt_videoid') else entry.id.split(':')[-1]

            # Check if we already have this video
            existing = Video.query.filter_by(
                channel_id=channel.id,
                video_id=video_id
            ).first()

            if existing:
                continue

            # Get full metadata
            video_url = f'https://www.youtube.com/watch?v={video_id}'
            metadata = self.downloader.get_video_metadata(video_url)

            if not metadata:
                continue

            # Classify as clip or full episode
            is_clip, reason = self.downloader.classify_video(
                metadata.get('title', ''),
                metadata.get('duration', 0),
                channel.clip_threshold_seconds
            )

            # Determine status
            if is_clip and not channel.download_clips:
                status = 'skipped'
            else:
                status = 'pending'

            # Create video record
            video = Video(
                video_id=video_id,
                channel_id=channel.id,
                title=metadata.get('title'),
                url=video_url,
                duration=metadata.get('duration'),
                upload_date=metadata.get('upload_date'),
                thumbnail_url=metadata.get('thumbnail_url'),
                is_clip=is_clip,
                classification_reason=reason,
                status=status,
            )

            db.session.add(video)
            new_videos.append(video)

        if new_videos:
            channel.video_count = Video.query.filter_by(channel_id=channel.id).count()
            db.session.commit()

        return new_videos

    def _check_via_ytdlp(self, channel: Channel) -> list:
        """Check channel via yt-dlp (for Rumble or fallback)."""
        videos = self.downloader.get_channel_videos(
            channel.url,
            max_videos=channel.backfill_limit if channel.backfill_enabled else 20
        )

        new_videos = []

        for video_data in videos:
            video_id = video_data.get('video_id')
            if not video_id:
                continue

            # Check if we already have this video
            existing = Video.query.filter_by(
                channel_id=channel.id,
                video_id=video_id
            ).first()

            if existing:
                continue

            # Get full metadata if needed
            video_url = video_data.get('url')
            duration = video_data.get('duration')

            if not duration:
                metadata = self.downloader.get_video_metadata(video_url)
                if metadata:
                    duration = metadata.get('duration')
                    video_data.update(metadata)

            # Classify
            is_clip, reason = self.downloader.classify_video(
                video_data.get('title', ''),
                duration or 0,
                channel.clip_threshold_seconds
            )

            # Determine status
            if is_clip and not channel.download_clips:
                status = 'skipped'
            else:
                status = 'pending'

            video = Video(
                video_id=video_id,
                channel_id=channel.id,
                title=video_data.get('title'),
                url=video_url,
                duration=duration,
                upload_date=video_data.get('upload_date'),
                thumbnail_url=video_data.get('thumbnail_url'),
                is_clip=is_clip,
                classification_reason=reason,
                status=status,
            )

            db.session.add(video)
            new_videos.append(video)

        if new_videos:
            channel.video_count = Video.query.filter_by(channel_id=channel.id).count()
            db.session.commit()

        return new_videos

    def _process_download_queue(self):
        """Process pending downloads."""
        with self.app.app_context():
            # Get pending videos (oldest first)
            pending = Video.query.filter_by(status='pending')\
                .order_by(Video.discovered_at.asc())\
                .limit(5).all()

            for video in pending:
                self._download_video(video)

    def _download_video(self, video: Video):
        """Download a single video."""
        channel = video.channel

        logger.info(f'Downloading: {video.title}')
        video.status = 'downloading'
        db.session.commit()

        try:
            result = self.downloader.download_video(
                video.url,
                channel.name,
                max_quality=channel.quality
            )

            if result['success']:
                video.status = 'completed'
                video.downloaded_at = datetime.utcnow()
                video.file_path = result['file_path']
                video.file_size = result['file_size']

                self._log_action(channel.id, video.id, 'download',
                               f'Downloaded: {video.title}',
                               {'file_size': result['file_size']})
            else:
                video.status = 'failed'
                video.error_message = result['error']

                self._log_action(channel.id, video.id, 'error',
                               f'Download failed: {result["error"]}')

            db.session.commit()

        except Exception as e:
            video.status = 'failed'
            video.error_message = str(e)
            db.session.commit()

            self._log_action(channel.id, video.id, 'error',
                           f'Download exception: {e}')

    def _log_action(self, channel_id: int, video_id: int, action: str,
                    message: str, details: dict = None):
        """Log an action."""
        log = DownloadLog(
            channel_id=channel_id,
            video_id=video_id,
            action=action,
            message=message,
            details=details,
        )
        db.session.add(log)
        db.session.commit()

    def check_channel_now(self, channel_id: int):
        """Manually trigger a channel check."""
        with self.app.app_context():
            channel = Channel.query.get(channel_id)
            if channel:
                Thread(target=self._check_channel, args=(channel,)).start()

    def download_video_now(self, video_id: int):
        """Manually trigger a video download."""
        with self.app.app_context():
            video = Video.query.get(video_id)
            if video and video.status in ('pending', 'failed'):
                Thread(target=self._download_video, args=(video,)).start()

    def backfill_channel(self, channel_id: int):
        """Trigger backfill for a channel."""
        with self.app.app_context():
            channel = Channel.query.get(channel_id)
            if channel:
                channel.backfill_enabled = True
                db.session.commit()
                Thread(target=self._check_channel, args=(channel,)).start()
