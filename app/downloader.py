"""Video downloader using yt-dlp library."""

import os
import re
import logging
import signal
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urljoin

import yt_dlp

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")


class VideoDownloader:
    """Handles video metadata extraction and downloading."""

    CLIP_KEYWORDS = [
        r'\bCLIP\b',
        r'\bHIGHLIGHT',
        r'\bSHORT\b',
        r'\bCOMPILATION\b',
        r'\bBEST\s+OF\b',
        r'\bMOMENTS\b',
        r'\bTOP\s+\d+',
        r'\bPREVIEW\b',
        r'\bTEASER\b',
        r'\bTRAILER\b',
    ]

    def __init__(self, download_path: str, max_quality: str = '1080'):
        self.download_path = download_path
        self.max_quality = max_quality
        os.makedirs(download_path, exist_ok=True)

    def _get_base_opts(self) -> dict:
        """Base yt-dlp options."""
        return {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

    def _clean_url(self, url: str) -> str:
        """Clean URL by removing query params and normalizing."""
        parsed = urlparse(url)
        # Remove query string and fragment
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        # Remove trailing slashes
        return clean.rstrip('/')

    def _parse_rumble_url(self, url: str) -> Optional[dict]:
        """
        Parse Rumble URL to extract channel info directly.

        Rumble URL formats:
        - Channel: https://rumble.com/c/channelname or https://rumble.com/c/channelname/videos
        - User: https://rumble.com/user/username
        - Video: https://rumble.com/v123abc-video-title.html
        """
        parsed = urlparse(url)
        if 'rumble.com' not in parsed.netloc:
            return None

        path = parsed.path.strip('/')
        parts = path.split('/')

        if not parts:
            return None

        # Channel URL: /c/channelname or /c/channelname/videos
        if parts[0] == 'c' and len(parts) >= 2:
            channel_name = parts[1]
            channel_url = f"https://rumble.com/c/{channel_name}"
            return {
                'name': channel_name,
                'url': channel_url,
                'platform': 'rumble',
                'channel_id': channel_name,
                'rss_url': None,
                'thumbnail': None,
                'video_title': None,
                'video_id': None,
                'is_channel_url': True,
            }

        # User URL: /user/username
        if parts[0] == 'user' and len(parts) >= 2:
            username = parts[1]
            user_url = f"https://rumble.com/user/{username}"
            return {
                'name': username,
                'url': user_url,
                'platform': 'rumble',
                'channel_id': username,
                'rss_url': None,
                'thumbnail': None,
                'video_title': None,
                'video_id': None,
                'is_channel_url': True,
            }

        # Video URL: /v123abc-video-title.html
        if parts[0].startswith('v') and parts[0].endswith('.html'):
            # This is a video URL - need to use yt-dlp to get channel info
            return None

        return None

    def extract_channel_info(self, url: str, timeout_seconds: int = 30) -> Optional[dict]:
        """Extract channel info from a video or channel URL."""
        # Clean the URL first
        clean_url = self._clean_url(url)

        # Try to parse Rumble URLs directly (faster, avoids timeout)
        rumble_info = self._parse_rumble_url(clean_url)
        if rumble_info and rumble_info.get('is_channel_url'):
            logger.info(f"Parsed Rumble channel URL directly: {rumble_info['name']}")
            return rumble_info

        # For video URLs or YouTube, use yt-dlp with timeout
        opts = self._get_base_opts()
        opts['socket_timeout'] = timeout_seconds

        try:
            # Set up timeout using signal (Unix only)
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)

            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(clean_url, download=False)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            if not info:
                return None

            # Detect platform
            platform = self._detect_platform(clean_url, info)

            # Extract channel details
            channel_id = info.get('channel_id') or info.get('uploader_id')
            channel_url = info.get('channel_url') or info.get('uploader_url')
            channel_name = info.get('channel') or info.get('uploader')

            # Build RSS URL for YouTube
            rss_url = None
            if platform == 'youtube' and channel_id:
                rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'

            return {
                'name': channel_name,
                'url': channel_url or clean_url,
                'platform': platform,
                'channel_id': channel_id,
                'rss_url': rss_url,
                'thumbnail': info.get('thumbnail'),
                # If this was a video URL, include video info
                'video_title': info.get('title') if info.get('id') else None,
                'video_id': info.get('id'),
            }
        except TimeoutError:
            logger.warning(f'Timeout extracting channel info from {url}')
            # For Rumble, try to parse the URL directly as fallback
            if 'rumble.com' in url:
                return self._parse_rumble_url(clean_url)
            return None
        except Exception as e:
            logger.error(f'Error extracting channel info from {url}: {e}')
            # For Rumble, try to parse the URL directly as fallback
            if 'rumble.com' in url:
                return self._parse_rumble_url(clean_url)
            return None

    def _detect_platform(self, url: str, info: dict) -> str:
        """Detect platform from URL or extractor info."""
        extractor = info.get('extractor', '').lower()

        if 'youtube' in extractor or 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'rumble' in extractor or 'rumble.com' in url:
            return 'rumble'
        else:
            return extractor or 'unknown'

    def get_video_metadata(self, url: str) -> Optional[dict]:
        """Get metadata for a single video without downloading."""
        opts = self._get_base_opts()

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return None

                return {
                    'video_id': info.get('id'),
                    'title': info.get('title'),
                    'url': info.get('webpage_url') or url,
                    'duration': info.get('duration'),
                    'upload_date': self._parse_date(info.get('upload_date')),
                    'thumbnail_url': info.get('thumbnail'),
                    'view_count': info.get('view_count'),
                    'description': info.get('description'),
                    'channel_name': info.get('channel') or info.get('uploader'),
                    'channel_id': info.get('channel_id') or info.get('uploader_id'),
                }
        except Exception as e:
            logger.error(f'Error getting video metadata for {url}: {e}')
            return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse yt-dlp date format (YYYYMMDD)."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y%m%d').date()
        except ValueError:
            return None

    def get_channel_videos(self, channel_url: str, max_videos: int = 50) -> list:
        """Get list of videos from a channel."""
        opts = self._get_base_opts()
        opts['extract_flat'] = True
        opts['playlist_items'] = f'1-{max_videos}'

        videos = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

                if not info:
                    return []

                entries = info.get('entries', [])
                for entry in entries:
                    if entry:
                        video_id = entry.get('id')
                        video_url = entry.get('url') or entry.get('webpage_url')

                        # Extract video_id from Rumble URL if not provided
                        if not video_id and video_url and 'rumble.com' in video_url:
                            video_id = self._extract_rumble_video_id(video_url)

                        videos.append({
                            'video_id': video_id,
                            'title': entry.get('title'),
                            'url': video_url,
                            'duration': entry.get('duration'),
                            'upload_date': self._parse_date(entry.get('upload_date')),
                        })
        except Exception as e:
            logger.error(f'Error getting channel videos from {channel_url}: {e}')

        return videos

    def _extract_rumble_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from Rumble URL.

        Rumble video URLs look like: https://rumble.com/v73rzhm-video-title.html
        The video ID is the part after /v and before the dash: v73rzhm
        """
        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            # Match pattern like v73rzhm-title.html
            match = re.match(r'^(v[a-zA-Z0-9]+)', path)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None

    def classify_video(self, title: str, duration: int,
                       clip_threshold: int = 300) -> tuple[bool, str]:
        """
        Classify video as clip or full episode.

        Returns:
            (is_clip, reason)
        """
        if not duration:
            return False, 'unknown_duration'

        # Check duration first
        if duration < clip_threshold:
            return True, f'duration_{duration}s_below_{clip_threshold}s'

        # Check title keywords
        if title:
            title_upper = title.upper()
            for pattern in self.CLIP_KEYWORDS:
                if re.search(pattern, title_upper):
                    return True, f'title_match_{pattern}'

        return False, 'full_episode'

    def download_video(self, url: str, channel_name: str,
                       max_quality: str = None,
                       progress_callback: callable = None) -> dict:
        """
        Download a video.

        Returns:
            {
                'success': bool,
                'file_path': str or None,
                'file_size': int or None,
                'error': str or None
            }
        """
        quality = max_quality or self.max_quality

        # Create channel subdirectory
        channel_dir = os.path.join(self.download_path, self._sanitize_filename(channel_name))
        os.makedirs(channel_dir, exist_ok=True)

        # Output template
        outtmpl = os.path.join(channel_dir, '%(upload_date)s - %(title)s.%(ext)s')

        # Format selection based on quality
        format_spec = self._get_format_spec(quality)

        opts = {
            'format': format_spec,
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            # Speed optimizations - download multiple fragments simultaneously
            'concurrent_fragment_downloads': 4,
            # Buffer and chunk sizes for faster throughput
            'buffersize': 1024 * 64,  # 64KB buffer
            'http_chunk_size': 10485760,  # 10MB chunks
            # Retries for reliability
            'retries': 10,
            'fragment_retries': 10,
            # Don't limit download rate - let it go as fast as possible
            'ratelimit': None,
            # Network optimizations
            'socket_timeout': 30,
        }

        if progress_callback:
            opts['progress_hooks'] = [progress_callback]

        result = {
            'success': False,
            'file_path': None,
            'file_size': None,
            'error': None,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info:
                    # Get the actual downloaded file path
                    file_path = ydl.prepare_filename(info)
                    # Handle extension change to mp4
                    base, ext = os.path.splitext(file_path)
                    mp4_path = base + '.mp4'

                    if os.path.exists(mp4_path):
                        file_path = mp4_path
                    elif os.path.exists(file_path):
                        pass
                    else:
                        # Try to find the file
                        for ext in ['.mp4', '.mkv', '.webm']:
                            if os.path.exists(base + ext):
                                file_path = base + ext
                                break

                    result['success'] = True
                    result['file_path'] = file_path
                    result['file_size'] = os.path.getsize(file_path) if os.path.exists(file_path) else None

        except yt_dlp.utils.DownloadError as e:
            result['error'] = str(e)
            logger.error(f'Download error for {url}: {e}')
        except Exception as e:
            result['error'] = str(e)
            logger.error(f'Unexpected error downloading {url}: {e}')

        return result

    def _get_format_spec(self, quality: str) -> str:
        """Get yt-dlp format specification for quality."""
        if quality == 'best':
            return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == '720':
            return 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]'
        elif quality == '1080':
            return 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]'
        elif quality == '480':
            return 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]'
        else:
            return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize string for use as filename."""
        # Remove or replace invalid characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
        sanitized = sanitized.strip('. ')
        return sanitized or 'unknown'
