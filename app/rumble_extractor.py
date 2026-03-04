"""Direct Rumble API extractor using the embedJS endpoint.

Bypasses yt-dlp for Rumble metadata by calling Rumble's embed API directly.
This is faster and avoids Cloudflare blocks that affect yt-dlp on Rumble.
"""

import json
import logging
import re
from datetime import datetime, date
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# Rumble embedJS API endpoint
EMBED_JS_URL = "https://rumble.com/embedJS/u3/?request=video&ver=2&v={video_id}"

# Timeout for HTTP requests (seconds)
REQUEST_TIMEOUT = 20

# Regex for matching Rumble video URLs in channel page HTML
# Matches href="/v<alphanum>-<slug>.html"
VIDEO_HREF_RE = re.compile(r'href="(/v[a-zA-Z0-9]+-[^"]+\.html)"')

# Regex for extracting the video ID from a Rumble video path or URL
# Rumble video IDs look like: v73rzhm  (letter v + alphanumeric)
VIDEO_ID_RE = re.compile(r'/(v[a-zA-Z0-9]+)-')


class RumbleExtractor:
    """
    Fetches Rumble channel and video metadata directly via Rumble's embed API.

    All public methods return plain dicts with keys that match what the rest of
    the app expects (same shape as VideoDownloader output), or None on failure.
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_channel_videos(self, channel_url: str, max_videos: int = 50) -> list[dict]:
        """
        Scrape a Rumble channel page for video links, then fetch metadata for
        each video via the embedJS API.

        Args:
            channel_url: Full Rumble channel URL, e.g.
                         https://rumble.com/c/SomeChannel
            max_videos:  Maximum number of videos to return.

        Returns:
            List of dicts: {video_id, title, url, duration, upload_date,
                            thumbnail_url, formats}
            Empty list on failure.
        """
        logger.info(f"Fetching channel page: {channel_url}")
        html = self._fetch_html(channel_url)
        if html is None:
            logger.error(f"Failed to fetch channel page: {channel_url}")
            return []

        video_paths = self._extract_video_paths(html)
        if not video_paths:
            logger.warning(f"No video links found on channel page: {channel_url}")
            return []

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_paths: list[str] = []
        for path in video_paths:
            if path not in seen:
                seen.add(path)
                unique_paths.append(path)

        unique_paths = unique_paths[:max_videos]
        logger.info(f"Found {len(unique_paths)} unique video links (capped at {max_videos})")

        results: list[dict] = []
        for path in unique_paths:
            video_url = f"https://rumble.com{path}"
            metadata = self.get_video_metadata(video_url)
            if metadata:
                results.append(metadata)

        logger.info(f"Successfully fetched metadata for {len(results)} videos")
        return results

    def get_video_metadata(self, video_url: str) -> Optional[dict]:
        """
        Fetch metadata for a single Rumble video via the embedJS API.

        Args:
            video_url: Full Rumble video URL, e.g.
                       https://rumble.com/v73rzhm-video-title.html

        Returns:
            Dict with keys: {video_id, title, url, duration, upload_date,
                             thumbnail_url, formats}
            formats is a list of {url, quality, ext} dicts.
            Returns None on failure.
        """
        video_id = self._extract_video_id(video_url)
        if not video_id:
            logger.error(f"Could not extract video ID from URL: {video_url}")
            return None

        api_url = EMBED_JS_URL.format(video_id=video_id)
        logger.debug(f"Fetching embedJS for {video_id}: {api_url}")

        try:
            response = curl_requests.get(
                api_url,
                impersonate="chrome",
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Network error fetching embedJS for {video_id}: {e}")
            return None

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"JSON parse error for embedJS response ({video_id}): {e}")
            return None

        return self._parse_embed_response(video_id, video_url, data)

    def extract_channel_info(self, channel_url: str) -> Optional[dict]:
        """
        Fetch channel metadata from a Rumble channel page.

        Args:
            channel_url: Full Rumble channel URL, e.g.
                         https://rumble.com/c/SomeChannel

        Returns:
            Dict with keys: {name, url, platform, channel_id, rss_url,
                             thumbnail}
            Returns None on failure.
        """
        logger.info(f"Extracting channel info from: {channel_url}")
        html = self._fetch_html(channel_url)
        if html is None:
            logger.error(f"Failed to fetch channel page for info: {channel_url}")
            return None

        channel_id = self._extract_channel_id_from_url(channel_url)
        name = self._extract_channel_name(html) or channel_id
        thumbnail = self._extract_og_image(html)

        return {
            "name": name,
            "url": channel_url,
            "platform": "rumble",
            "channel_id": channel_id,
            "rss_url": None,
            "thumbnail": thumbnail,
        }

    # ------------------------------------------------------------------ #
    # Private helpers - HTTP                                               #
    # ------------------------------------------------------------------ #

    def _fetch_html(self, url: str) -> Optional[str]:
        """Fetch a page via curl_cffi and return the response text."""
        try:
            response = curl_requests.get(
                url,
                impersonate="chrome",
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Private helpers - parsing                                            #
    # ------------------------------------------------------------------ #

    def _extract_video_paths(self, html: str) -> list[str]:
        """
        Find all Rumble video href paths in channel page HTML.

        Returns a list of path strings like ['/v73rzhm-title.html', ...].
        """
        return VIDEO_HREF_RE.findall(html)

    def _extract_video_id(self, video_url: str) -> Optional[str]:
        """
        Extract the Rumble video ID from a video URL or path.

        Rumble video URLs:   https://rumble.com/v73rzhm-video-title.html
        Extracted ID:        v73rzhm
        """
        try:
            parsed = urlparse(video_url)
            path = parsed.path
            match = VIDEO_ID_RE.search(path)
            if match:
                return match.group(1)
            # Fallback: handle paths that end with .html but have no dash
            # e.g. /v73rzhm.html (unusual but guard against it)
            fallback = re.search(r'/(v[a-zA-Z0-9]+)(?:\.html)?$', path)
            if fallback:
                return fallback.group(1)
        except Exception as e:
            logger.error(f"Error extracting video ID from {video_url}: {e}")
        return None

    def _parse_embed_response(
        self, video_id: str, video_url: str, data: dict
    ) -> Optional[dict]:
        """
        Parse the embedJS API JSON response into our standard metadata dict.

        Expected input shape:
        {
            "title": "Video Title",
            "author": {"name": "ChannelName", "url": "/c/ChannelName"},
            "duration": 1234,
            "pubDate": "2024-01-15T12:00:00+00:00",
            "i": "https://thumbnail-url...",
            "ua": {
                "mp4": {
                    "360":  {"url": "https://..."},
                    "480":  {"url": "https://..."},
                    "720":  {"url": "https://..."},
                    "1080": {"url": "https://..."}
                }
            }
        }
        """
        title = data.get("title")
        duration = data.get("duration")  # already in seconds
        thumbnail_url = data.get("i")
        pub_date_str = data.get("pubDate")

        upload_date = self._parse_pub_date(pub_date_str)

        # Extract MP4 format URLs
        formats = self._parse_formats(data)

        # Best URL: highest quality MP4, fall back to original video_url
        best_url = self._pick_best_url(formats) or video_url

        return {
            "video_id": video_id,
            "title": title,
            "url": best_url,
            "duration": duration,
            "upload_date": upload_date,
            "thumbnail_url": thumbnail_url,
            "formats": formats,
        }

    def _parse_formats(self, data: dict) -> list[dict]:
        """
        Extract available MP4 formats from the embedJS response.

        Returns a list of {url, quality, ext} dicts sorted by quality ascending.
        """
        formats: list[dict] = []
        try:
            ua = data.get("ua", {})
            mp4_entries = ua.get("mp4", {})
            for quality, info in mp4_entries.items():
                url = info.get("url") if isinstance(info, dict) else None
                if url:
                    formats.append({
                        "url": url,
                        "quality": quality,
                        "ext": "mp4",
                    })
        except Exception as e:
            logger.error(f"Error parsing formats from embedJS response: {e}")

        # Sort by numeric quality value so callers can easily pick best/worst
        def _quality_key(f: dict) -> int:
            try:
                return int(f["quality"])
            except (ValueError, KeyError):
                return 0

        formats.sort(key=_quality_key)
        return formats

    def _pick_best_url(self, formats: list[dict]) -> Optional[str]:
        """Return the URL for the highest quality format available."""
        if not formats:
            return None
        # formats is sorted ascending by quality; last entry is highest
        return formats[-1]["url"]

    def _parse_pub_date(self, pub_date_str: Optional[str]) -> Optional[date]:
        """
        Parse an ISO 8601 pubDate string from the embedJS API into a date object.

        Examples:
            "2024-01-15T12:00:00+00:00"  -> date(2024, 1, 15)
            "2024-01-15"                 -> date(2024, 1, 15)
        """
        if not pub_date_str:
            return None
        # Slice off the first 19 characters to get "YYYY-MM-DDTHH:MM:SS"
        # This strips any timezone suffix before strptime sees it.
        truncated = pub_date_str[:19]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(truncated, fmt).date()
            except ValueError:
                continue
        # Generic fallback using fromisoformat for any other ISO 8601 variant
        try:
            return datetime.fromisoformat(pub_date_str).date()
        except ValueError:
            pass
        logger.warning(f"Could not parse pubDate: {pub_date_str!r}")
        return None

    def _extract_channel_id_from_url(self, url: str) -> Optional[str]:
        """
        Extract channel identifier from a Rumble channel URL.

            https://rumble.com/c/ChannelName   -> ChannelName
            https://rumble.com/user/UserName   -> UserName
        """
        try:
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            parts = path.split("/")
            if len(parts) >= 2 and parts[0] in ("c", "user"):
                return parts[1]
        except Exception as e:
            logger.error(f"Error extracting channel ID from {url}: {e}")
        return None

    def _extract_channel_name(self, html: str) -> Optional[str]:
        """
        Extract the channel display name from channel page HTML.

        Tries Open Graph title tag first, then falls back to <title>.
        OG title is preferred because it usually has the clean channel name
        without the " - Rumble" suffix.
        """
        # Try og:title meta tag
        og_match = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if og_match:
            return og_match.group(1).strip()

        # Fall back to <title> tag, stripping common suffixes
        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            raw = title_match.group(1).strip()
            # Strip " - Rumble" or " | Rumble" suffixes
            name = re.sub(r'\s*[-|]\s*Rumble\s*$', '', raw, flags=re.IGNORECASE)
            return name.strip() or None

        return None

    def _extract_og_image(self, html: str) -> Optional[str]:
        """Extract og:image URL from channel page HTML for the channel thumbnail."""
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return None
