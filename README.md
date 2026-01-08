# Video Downloader

A self-hosted web application for automatically downloading videos from YouTube and Rumble channels on a schedule.

## Features

- **Web UI** for managing channels and monitoring downloads
- **Multi-platform support**: YouTube and Rumble
- **Smart channel detection**: Paste any video URL to automatically find and add the channel
- **Clip filtering**: Automatically classify and optionally skip short clips vs full episodes
- **Scheduled checks**: Configurable per-channel check intervals
- **Backfill support**: Download existing videos when adding a channel
- **Quality control**: Set maximum download quality per channel
- **Download tracking**: SQLite database tracks all videos and their status

## Screenshots

The web interface provides:
- Dashboard with statistics
- Channel management (add, edit, delete)
- Video list with filtering by status
- Download logs

## Quick Start

### Using Docker Compose (Recommended)

1. Clone this repository:
   ```bash
   git clone https://github.com/nullEFFORT/rumble-downloader.git
   cd rumble-downloader
   ```

2. Create download directory:
   ```bash
   mkdir -p /opt/homelab/data/video-downloader/downloads
   ```

3. Start the container:
   ```bash
   docker-compose up -d
   ```

4. Access the web UI at `http://localhost:5050`

### Manual Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install ffmpeg:
   ```bash
   # Ubuntu/Debian
   apt install ffmpeg

   # macOS
   brew install ffmpeg
   ```

3. Run the application:
   ```bash
   python run.py
   ```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-change-me` | Flask secret key |
| `DATABASE_URL` | `sqlite:////data/videodownloader.db` | Database connection string |
| `DOWNLOAD_PATH` | `/downloads` | Where to store downloaded videos |
| `TZ` | `UTC` | Timezone for scheduling |

### Channel Options

When adding a channel, you can configure:

- **Check interval**: How often to check for new videos (1-168 hours)
- **Quality**: Maximum video quality (480p, 720p, 1080p, or best)
- **Download clips**: Include short videos (< clip threshold)
- **Clip threshold**: Duration in seconds to classify as clip (default: 300)
- **Backfill**: Download existing videos when adding channel
- **Backfill limit**: Maximum videos to backfill (default: 50)

## Usage

### Adding a Channel

1. Go to the Dashboard
2. Paste a YouTube or Rumble URL (video or channel)
3. Click "Discover" to detect the channel
4. Configure options
5. Click "Add Channel"

### Managing Videos

- Videos are automatically checked based on the channel's schedule
- New videos are queued for download
- Clips are automatically detected and can be skipped
- Failed downloads can be retried manually

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/channels` | GET | List all channels |
| `/api/channels` | POST | Add a channel |
| `/api/channels/<id>` | PUT | Update channel settings |
| `/api/channels/<id>` | DELETE | Delete channel |
| `/api/channels/<id>/check` | POST | Trigger immediate check |
| `/api/channels/discover` | POST | Discover channel from URL |
| `/api/videos` | GET | List videos (with filters) |
| `/api/videos/<id>/download` | POST | Queue video for download |
| `/api/stats` | GET | Get download statistics |

## Architecture

```
video-downloader/
├── app/
│   ├── __init__.py      # Flask app factory
│   ├── models.py        # SQLAlchemy models (Channel, Video, Log)
│   ├── routes.py        # Web UI and API routes
│   ├── downloader.py    # yt-dlp wrapper for downloads
│   ├── scheduler.py     # APScheduler for background tasks
│   ├── static/          # CSS and JS
│   └── templates/       # Jinja2 templates
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── run.py
```

## Clip Detection

Videos are classified as clips based on:
1. **Duration**: Videos shorter than the threshold (default 5 min)
2. **Title keywords**: CLIP, HIGHLIGHT, SHORT, COMPILATION, etc.

You can configure the threshold per channel and choose whether to download clips.

## Troubleshooting

### Videos not downloading

1. Check the Logs page for error messages
2. Ensure ffmpeg is installed in the container
3. Verify the download path is writable

### Channel not found

1. Try pasting a direct video URL instead of channel URL
2. Check if the URL is accessible
3. Some private/age-restricted content may not work

### High disk usage

1. Set quality limits per channel
2. Disable backfill for channels with large archives
3. Enable clip filtering to skip short videos

## License

MIT License
