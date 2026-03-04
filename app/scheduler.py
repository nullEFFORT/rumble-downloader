"""Background scheduler for channel checking and video downloading."""

import fcntl
import logging
from datetime import datetime, timedelta
from threading import Thread, Event, Lock
from typing import Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import feedparser

from .models import db, Channel, Video, DownloadLog
from .downloader import VideoDownloader
from .rumble_extractor import RumbleExtractor
from .notifications import NotificationManager

logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
    """Raised when a download is cancelled by user."""
    pass


class DownloadScheduler:
    """Manages scheduled channel checks and downloads with queue control."""

    def __init__(self, app=None, download_path: str = '/downloads', max_concurrent_downloads: int = 2):
        self.scheduler = BackgroundScheduler()
        self.downloader = VideoDownloader(download_path)
        self.rumble_extractor = RumbleExtractor()
        self.notifier = NotificationManager()
        self.app = app
        self.download_path = download_path
        self._is_running = False

        # Queue control
        self._queue_paused = False
        self._queue_lock = Lock()
        self._max_concurrent_downloads = max_concurrent_downloads  # Download multiple videos at once

        # Active downloads tracking: {video_id: {"thread": Thread, "cancel_event": Event, "progress": dict}}
        self._active_downloads: Dict[int, dict] = {}
        self._downloads_lock = Lock()

    def init_app(self, app):
        """Initialize with Flask app."""
        self.app = app
        self.download_path = app.config.get('DOWNLOAD_PATH', '/downloads')
        self.downloader = VideoDownloader(self.download_path)

    def start(self):
        """Start the scheduler with file lock to prevent duplicate instances."""
        if self._is_running:
            return

        # Acquire file lock to prevent multiple scheduler instances (e.g. gunicorn preforking)
        lock_path = '/tmp/rumble-downloader-scheduler.lock'
        self._lock_file = open(lock_path, 'w')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            logger.info('Another scheduler instance holds the lock, skipping start')
            self._lock_file.close()
            return

        # Add job to check all channels periodically
        self.scheduler.add_job(
            self._check_all_channels,
            IntervalTrigger(hours=1),
            id='check_channels',
            name='Check all channels for new videos',
            replace_existing=True,
        )

        # Add job to process download queue - check every 30 seconds for faster starts
        self.scheduler.add_job(
            self._process_download_queue,
            IntervalTrigger(seconds=30),
            id='process_downloads',
            name='Process pending downloads',
            replace_existing=True,
        )

        self.scheduler.start()
        self._is_running = True
        logger.info('Download scheduler started')

    def stop(self):
        """Stop the scheduler and release the file lock."""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            if hasattr(self, '_lock_file') and self._lock_file:
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
                self._lock_file.close()
            logger.info('Download scheduler stopped')

    # ==================== Queue Control API ====================

    def pause_queue(self):
        """Pause the download queue (won't start new downloads)."""
        with self._queue_lock:
            self._queue_paused = True
            logger.info('Download queue paused')

    def resume_queue(self):
        """Resume the download queue."""
        with self._queue_lock:
            self._queue_paused = False
            logger.info('Download queue resumed')

    def is_queue_paused(self) -> bool:
        """Check if queue is paused."""
        with self._queue_lock:
            return self._queue_paused

    def get_queue_status(self) -> dict:
        """Get current queue status."""
        with self._downloads_lock:
            active = []
            for video_id, info in self._active_downloads.items():
                active.append({
                    'video_id': video_id,
                    'title': info.get('title'),
                    'progress': info.get('progress', {}),
                })

        return {
            'paused': self.is_queue_paused(),
            'active_downloads': active,
            'active_count': len(active),
        }

    def cancel_download(self, video_id: int) -> bool:
        """Cancel an active download."""
        with self._downloads_lock:
            if video_id in self._active_downloads:
                self._active_downloads[video_id]['cancel_event'].set()
                logger.info(f'Cancellation requested for video {video_id}')
                return True
        return False

    def cancel_all_downloads(self):
        """Cancel all active downloads."""
        with self._downloads_lock:
            for video_id, info in self._active_downloads.items():
                info['cancel_event'].set()
            logger.info(f'Cancellation requested for all {len(self._active_downloads)} active downloads')

    def get_active_download_ids(self) -> list:
        """Get list of video IDs currently downloading."""
        with self._downloads_lock:
            return list(self._active_downloads.keys())

    # ==================== Channel Checking ====================

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
        logger.info(f'Starting check for channel: {channel.name} (platform: {channel.platform})')
        try:
            new_videos = []

            if channel.platform == 'youtube' and channel.rss_url:
                # Use RSS for YouTube (faster)
                logger.info(f'Using RSS for YouTube channel: {channel.name}')
                new_videos = self._check_youtube_rss(channel)
            elif channel.platform == 'rumble':
                # Use direct Rumble embedJS API (faster, bypasses Cloudflare)
                logger.info(f'Using Rumble extractor for channel: {channel.name}')
                new_videos = self._check_via_rumble_api(channel)
            else:
                # Fall back to yt-dlp for YouTube without RSS
                logger.info(f'Using yt-dlp for channel: {channel.name} (URL: {channel.url})')
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
            self.notifier.notify_channel_error(channel.name, str(e))

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

            self.notifier.notify_new_videos(
                channel.name,
                len(new_videos),
                [v.title for v in new_videos[:5]]
            )

        return new_videos

    def _check_via_rumble_api(self, channel: Channel) -> list:
        """Check Rumble channel using direct embedJS API."""
        videos = self.rumble_extractor.get_channel_videos(
            channel.url,
            max_videos=channel.backfill_limit if channel.backfill_enabled else 20
        )
        logger.info(f'Rumble API returned {len(videos)} videos for {channel.name}')

        new_videos = []
        for video_data in videos:
            video_id = video_data.get('video_id')
            if not video_id:
                continue

            existing = Video.query.filter_by(
                channel_id=channel.id,
                video_id=video_id
            ).first()
            if existing:
                continue

            video_url = video_data.get('url')
            duration = video_data.get('duration')

            is_clip, reason = self.downloader.classify_video(
                video_data.get('title', ''),
                duration or 0,
                channel.clip_threshold_seconds
            )

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
            logger.info(f'Added video: {video_id} - {video_data.get("title", "Unknown")[:50]}')

        if new_videos:
            channel.video_count = Video.query.filter_by(channel_id=channel.id).count()
            db.session.commit()

            # Send notification for new videos
            self.notifier.notify_new_videos(
                channel.name,
                len(new_videos),
                [v.title for v in new_videos[:5]]
            )

        return new_videos

    def _check_via_ytdlp(self, channel: Channel) -> list:
        """Check channel via yt-dlp (for Rumble or fallback)."""
        logger.info(f'Fetching videos from {channel.url} via yt-dlp...')
        videos = self.downloader.get_channel_videos(
            channel.url,
            max_videos=channel.backfill_limit if channel.backfill_enabled else 20
        )
        logger.info(f'yt-dlp returned {len(videos)} videos for {channel.name}')

        # Log first video data for debugging
        if videos:
            logger.info(f'Sample video data: {videos[0]}')

        new_videos = []

        for idx, video_data in enumerate(videos):
            video_id = video_data.get('video_id')
            if not video_id:
                logger.debug(f'Skipping video {idx}: no video_id. Data: {video_data}')
                continue

            logger.debug(f'Processing video {idx}: {video_id} - {video_data.get("title", "Unknown")}')

            # Check if we already have this video
            existing = Video.query.filter_by(
                channel_id=channel.id,
                video_id=video_id
            ).first()

            if existing:
                logger.debug(f'Video {video_id} already exists, skipping')
                continue

            # Get full metadata if needed
            video_url = video_data.get('url')
            duration = video_data.get('duration')

            # Build proper URL for Rumble if needed
            if video_url and not video_url.startswith('http'):
                video_url = f'https://rumble.com{video_url}' if video_url.startswith('/') else f'https://rumble.com/{video_url}'
                logger.debug(f'Fixed video URL: {video_url}')

            if not duration and video_url:
                logger.debug(f'Fetching metadata for {video_url}')
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
            logger.info(f'Added video: {video_id} - {video_data.get("title", "Unknown")[:50]}')

        logger.info(f'Processed {len(videos)} videos, found {len(new_videos)} new videos to add')

        if new_videos:
            channel.video_count = Video.query.filter_by(channel_id=channel.id).count()
            db.session.commit()

            self.notifier.notify_new_videos(
                channel.name,
                len(new_videos),
                [v.title for v in new_videos[:5]]
            )

        return new_videos

    # ==================== Download Processing ====================

    def _process_download_queue(self):
        """Process pending downloads with concurrent download support."""
        # Check if queue is paused
        if self.is_queue_paused():
            logger.debug('Queue is paused, skipping download processing')
            return

        with self.app.app_context():
            # Check how many downloads are currently active
            with self._downloads_lock:
                active_count = len(self._active_downloads)

            # Calculate how many more downloads we can start
            slots_available = self._max_concurrent_downloads - active_count
            if slots_available <= 0:
                logger.debug(f'Max concurrent downloads reached ({active_count}/{self._max_concurrent_downloads})')
                return

            # Get pending videos ordered by priority (desc), then discovered_at (asc)
            pending = Video.query.filter_by(status='pending')\
                .order_by(Video.priority.desc(), Video.discovered_at.asc())\
                .limit(slots_available).all()

            for video in pending:
                # Check again if paused (could have been paused while iterating)
                if self.is_queue_paused():
                    break

                # Check if already downloading
                with self._downloads_lock:
                    if video.id in self._active_downloads:
                        continue

                # Start download in background thread
                cancel_event = Event()
                thread = Thread(target=self._download_video_thread, args=(video.id, cancel_event))
                thread.daemon = True
                thread.start()

                logger.info(f'Started concurrent download for video {video.id}: {video.title}')

    def _download_video_thread(self, video_id: int, cancel_event: Event):
        """Thread wrapper for downloading a video with proper app context."""
        try:
            with self.app.app_context():
                video = Video.query.get(video_id)
                if video and video.status == 'pending':
                    self._download_video(video, cancel_event)
        except Exception as e:
            logger.error(f'Error in download thread for video {video_id}: {e}', exc_info=True)

    def _download_video(self, video: Video, cancel_event: Event = None):
        """Download a single video with cancellation support."""
        channel = video.channel

        # Create cancel event if not provided
        if cancel_event is None:
            cancel_event = Event()

        # Track this download
        with self._downloads_lock:
            self._active_downloads[video.id] = {
                'title': video.title,
                'cancel_event': cancel_event,
                'progress': {'status': 'starting', 'percent': 0},
            }

        logger.info(f'Downloading: {video.title}')
        video.status = 'downloading'
        db.session.commit()

        def progress_hook(d):
            """Progress hook that checks for cancellation."""
            # Check for cancellation
            if cancel_event.is_set():
                raise DownloadCancelled(f"Download cancelled for video {video.id}")

            # Update progress
            with self._downloads_lock:
                if video.id in self._active_downloads:
                    if d['status'] == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                        downloaded = d.get('downloaded_bytes', 0)
                        percent = (downloaded / total * 100) if total > 0 else 0
                        speed = d.get('speed', 0)
                        eta = d.get('eta', 0)
                        self._active_downloads[video.id]['progress'] = {
                            'status': 'downloading',
                            'percent': round(percent, 1),
                            'downloaded': downloaded,
                            'total': total,
                            'speed': speed,
                            'eta': eta,
                        }
                    elif d['status'] == 'finished':
                        self._active_downloads[video.id]['progress'] = {
                            'status': 'processing',
                            'percent': 100,
                        }

        try:
            result = self.downloader.download_video(
                video.url,
                channel.name,
                max_quality=channel.quality,
                audio_only=channel.audio_only,
                clip_start=video.clip_start,
                clip_end=video.clip_end,
                progress_callback=progress_hook
            )

            if result['success']:
                video.status = 'completed'
                video.downloaded_at = datetime.utcnow()
                video.file_path = result['file_path']
                video.file_size = result['file_size']

                self._log_action(channel.id, video.id, 'download',
                               f'Downloaded: {video.title}',
                               {'file_size': result['file_size']})

                self.notifier.notify_download_complete(
                    video.title, channel.name,
                    file_size=result['file_size'],
                    duration=video.duration
                )
            else:
                video.status = 'failed'
                video.error_message = result['error']

                self._log_action(channel.id, video.id, 'error',
                               f'Download failed: {result["error"]}')

                self.notifier.notify_download_failed(
                    video.title, channel.name, result['error']
                )

            db.session.commit()

        except DownloadCancelled:
            video.status = 'pending'  # Back to pending so it can be retried
            video.error_message = 'Cancelled by user'
            db.session.commit()

            self._log_action(channel.id, video.id, 'cancel',
                           f'Download cancelled: {video.title}')
            logger.info(f'Download cancelled for video {video.id}')

        except Exception as e:
            video.status = 'failed'
            video.error_message = str(e)
            db.session.commit()

            self._log_action(channel.id, video.id, 'error',
                           f'Download exception: {e}')

        finally:
            # Remove from active downloads
            with self._downloads_lock:
                self._active_downloads.pop(video.id, None)

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

    # ==================== Manual Triggers ====================

    def check_channel_now(self, channel_id: int):
        """Manually trigger a channel check."""
        def do_check():
            try:
                with self.app.app_context():
                    logger.info(f'Manual check triggered for channel {channel_id}')
                    channel = Channel.query.get(channel_id)
                    if channel:
                        self._check_channel(channel)
                    else:
                        logger.warning(f'Channel {channel_id} not found')
            except Exception as e:
                logger.error(f'Error in check_channel_now thread: {e}', exc_info=True)
        Thread(target=do_check).start()

    def download_video_now(self, video_id: int):
        """Manually trigger a video download."""
        def do_download():
            try:
                with self.app.app_context():
                    logger.info(f'Manual download triggered for video {video_id}')
                    video = Video.query.get(video_id)
                    if video and video.status in ('pending', 'failed'):
                        cancel_event = Event()
                        self._download_video(video, cancel_event)
            except Exception as e:
                logger.error(f'Error in download_video_now thread: {e}', exc_info=True)
        Thread(target=do_download).start()

    def backfill_channel(self, channel_id: int):
        """Trigger backfill for a channel."""
        def do_backfill():
            try:
                with self.app.app_context():
                    logger.info(f'Backfill triggered for channel {channel_id}')
                    channel = Channel.query.get(channel_id)
                    if channel:
                        channel.backfill_enabled = True
                        db.session.commit()
                        self._check_channel(channel)
            except Exception as e:
                logger.error(f'Error in backfill_channel thread: {e}', exc_info=True)
        Thread(target=do_backfill).start()
