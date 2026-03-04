"""Discord webhook notifications for download events."""

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationManager:
    """Sends Discord webhook notifications for Rumble Downloader events."""

    def __init__(self, webhook_url: str = None):
        self._webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
        if not self._webhook_url:
            logger.debug("No Discord webhook URL configured; notifications disabled.")

    def is_enabled(self) -> bool:
        """Return True if a webhook URL is configured."""
        return bool(self._webhook_url)

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    def notify_download_complete(
        self,
        video_title: str,
        channel_name: str,
        file_size: int = None,
        duration: int = None,
    ) -> bool:
        """Send a green embed indicating a successful download."""
        fields = [
            {"name": "Title", "value": video_title or "Unknown", "inline": False},
            {"name": "Channel", "value": channel_name or "Unknown", "inline": True},
        ]
        if file_size is not None:
            fields.append(
                {"name": "File Size", "value": self._format_size(file_size), "inline": True}
            )
        if duration is not None:
            fields.append(
                {"name": "Duration", "value": self._format_duration(duration), "inline": True}
            )

        payload = self._build_payload(
            title="Download Complete",
            color=0x00FF00,
            fields=fields,
        )
        return self._send_webhook(payload)

    def notify_download_failed(
        self,
        video_title: str,
        channel_name: str,
        error: str,
    ) -> bool:
        """Send a red embed indicating a failed download."""
        fields = [
            {"name": "Title", "value": video_title or "Unknown", "inline": False},
            {"name": "Channel", "value": channel_name or "Unknown", "inline": True},
            {"name": "Error", "value": error or "Unknown error", "inline": False},
        ]
        payload = self._build_payload(
            title="Download Failed",
            color=0xFF0000,
            fields=fields,
        )
        return self._send_webhook(payload)

    def notify_new_videos(
        self,
        channel_name: str,
        count: int,
        video_titles: list = None,
    ) -> bool:
        """Send a blue embed when new videos are discovered on a channel."""
        description_parts = [f"{count} new video{'s' if count != 1 else ''} found."]

        if video_titles:
            visible = video_titles[:5]
            lines = "\n".join(f"- {t}" for t in visible)
            if len(video_titles) > 5:
                lines += f"\n... and {len(video_titles) - 5} more"
            description_parts.append(lines)

        fields = [
            {"name": "Channel", "value": channel_name or "Unknown", "inline": True},
            {"name": "New Videos", "value": str(count), "inline": True},
        ]
        payload = self._build_payload(
            title="New Videos Detected",
            color=0x0099FF,
            description="\n".join(description_parts),
            fields=fields,
        )
        return self._send_webhook(payload)

    def notify_channel_error(
        self,
        channel_name: str,
        error: str,
    ) -> bool:
        """Send an orange embed when a channel check encounters an error."""
        fields = [
            {"name": "Channel", "value": channel_name or "Unknown", "inline": True},
            {"name": "Error", "value": error or "Unknown error", "inline": False},
        ]
        payload = self._build_payload(
            title="Channel Error",
            color=0xFF9900,
            fields=fields,
        )
        return self._send_webhook(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        title: str,
        color: int,
        fields: list,
        description: str = None,
    ) -> dict:
        """Construct a Discord webhook payload with a single embed."""
        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "footer": {"text": "Rumble Downloader"},
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if description:
            embed["description"] = description
        return {"embeds": [embed]}

    def _send_webhook(self, payload: dict) -> bool:
        """POST JSON payload to the Discord webhook URL.

        Returns True on a 2xx response, False on any error.
        Never raises exceptions.
        """
        if not self.is_enabled():
            return False

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self._webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                status = response.status
                if 200 <= status < 300:
                    return True
                logger.warning("Discord webhook returned unexpected status %s", status)
                return False
        except urllib.error.HTTPError as exc:
            logger.error("Discord webhook HTTP error %s: %s", exc.code, exc.reason)
        except urllib.error.URLError as exc:
            logger.error("Discord webhook URL error: %s", exc.reason)
        except Exception as exc:
            logger.error("Discord webhook unexpected error: %s", exc)
        return False

    @staticmethod
    def _format_size(bytes_: int) -> str:
        """Format a byte count into a human-readable string."""
        if bytes_ is None:
            return "Unknown"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if bytes_ < 1024:
                return f"{bytes_:.1f} {unit}" if unit != "B" else f"{bytes_} B"
            bytes_ /= 1024
        return f"{bytes_:.1f} PB"

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format a duration in seconds to HH:MM:SS or MM:SS."""
        if seconds is None:
            return "Unknown"
        seconds = int(seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
