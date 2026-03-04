# Rumble Downloader

A self-hosted web application for automatically downloading videos from YouTube and Rumble channels on a schedule. Features smart clip filtering, audio-only mode, Discord notifications, optional authentication, and a real-time download queue.

## Features

- **Multi-platform support**: YouTube and Rumble with per-platform optimizations
- **Direct Rumble API**: Uses Rumble's embedJS endpoint for fast metadata extraction, bypassing Cloudflare
- **Cloudflare bypass**: TLS fingerprint impersonation via curl-cffi
- **Smart clip filtering**: Auto-classify and skip short clips vs full episodes
- **Audio-only mode**: Extract MP3 audio per channel (great for podcasts)
- **Timestamp clipping**: Download specific segments with start/end timestamps
- **Scheduled checks**: Configurable per-channel check intervals
- **Backfill support**: Download existing videos when adding a channel
- **Quality control**: Set maximum download quality per channel
- **Concurrent downloads**: Download multiple videos simultaneously
- **Priority system**: Higher priority videos download first
- **Queue control**: Real-time pause/resume, cancel individual or all downloads
- **Discord notifications**: Webhook alerts for downloads, new videos, and errors
- **Optional authentication**: Protect the UI with username/password
- **Database migrations**: Alembic/Flask-Migrate for safe schema upgrades
- **Web UI**: Dashboard with queue panel, channel management, video browser, logs

## Quick Start

### Docker Compose (Recommended)

```bash
git clone https://github.com/nullEFFORT/rumble-downloader.git
cd rumble-downloader
mkdir -p data
docker compose up -d
```

Access the web UI at `http://localhost:5050`

### Manual Installation

```bash
pip install -r requirements.txt
apt install ffmpeg  # or: brew install ffmpeg
python run.py
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret (change in production) |
| `DATABASE_URL` | `sqlite:////data/videodownloader.db` | Database connection string |
| `DOWNLOAD_PATH` | `/downloads` | Where to store downloaded videos |
| `TZ` | `UTC` | Timezone for scheduling |
| `AUTH_USERNAME` | *(disabled)* | Set to enable login requirement |
| `AUTH_PASSWORD` | *(disabled)* | Set with AUTH_USERNAME to enable auth |
| `DISCORD_WEBHOOK_URL` | *(disabled)* | Discord webhook for download notifications |

### Channel Options

| Option | Default | Description |
|--------|---------|-------------|
| Check interval | 6 hours | How often to check for new videos |
| Quality | 1080p | Max video quality (480p, 720p, 1080p, best) |
| Audio only | Off | Extract MP3 instead of video |
| Download clips | Off | Include short videos below threshold |
| Clip threshold | 300s | Duration cutoff for clip classification |
| Backfill | Off | Download existing videos on add |
| Backfill limit | 50 | Max videos to backfill |

## Usage

### Adding a Channel

1. Go to the Dashboard
2. Paste a YouTube or Rumble URL (video or channel)
3. Click **Discover** to detect the channel
4. Configure options (quality, audio-only, clips, etc.)
5. Click **Add Channel**

### Download Queue

- **Pause/Resume**: Stop starting new downloads
- **Cancel All**: Cancel all active downloads
- **Active Downloads**: Real-time progress with speed and ETA
- **Cancel Individual**: Cancel specific downloads

### Timestamp Clipping

Set start/end timestamps on any video before downloading:
```
POST /api/videos/<id>/clip
{"clip_start": "1:30", "clip_end": "5:45"}
```

Accepts formats: `HH:MM:SS`, `MM:SS`, or raw seconds.

### Discord Notifications

Set `DISCORD_WEBHOOK_URL` to receive alerts for:
- New videos discovered on channels
- Downloads completed (with file size and duration)
- Download failures (with error details)
- Channel check errors

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/channels` | GET | List all channels |
| `/api/channels` | POST | Add a channel |
| `/api/channels/<id>` | PUT | Update channel settings |
| `/api/channels/<id>` | DELETE | Delete channel |
| `/api/channels/<id>/check` | POST | Trigger immediate check |
| `/api/channels/<id>/backfill` | POST | Backfill channel videos |
| `/api/channels/discover` | POST | Discover channel from URL |
| `/api/videos` | GET | List videos (with filters) |
| `/api/videos/<id>/download` | POST | Queue video for download |
| `/api/videos/<id>/skip` | POST | Mark video as skipped |
| `/api/videos/<id>/unskip` | POST | Move skipped video to pending |
| `/api/videos/<id>/cancel` | POST | Cancel active download |
| `/api/videos/<id>/priority` | POST | Set download priority |
| `/api/videos/<id>/clip` | POST | Set timestamp clip range |
| `/api/videos/<id>/play` | GET | Stream downloaded video |
| `/api/videos/<id>/delete-file` | POST | Delete downloaded file |
| `/api/videos/bulk-skip` | POST | Skip multiple videos |
| `/api/videos/bulk-priority` | POST | Set priority for multiple |
| `/api/queue/status` | GET | Queue status + active downloads |
| `/api/queue/pause` | POST | Pause download queue |
| `/api/queue/resume` | POST | Resume download queue |
| `/api/queue/cancel-all` | POST | Cancel all active downloads |
| `/api/stats` | GET | Download statistics |

## Architecture

```
rumble-downloader/
├── app/
│   ├── __init__.py          # Flask app factory, migrations
│   ├── models.py            # SQLAlchemy models (Channel, Video, Log)
│   ├── routes.py            # Web UI and API routes
│   ├── downloader.py        # yt-dlp wrapper (video/audio/clip)
│   ├── scheduler.py         # APScheduler background tasks
│   ├── rumble_extractor.py  # Direct Rumble embedJS API client
│   ├── notifications.py     # Discord webhook notifications
│   ├── auth.py              # Optional session-based authentication
│   ├── static/              # CSS and JS
│   └── templates/           # Jinja2 templates
├── migrations/              # Alembic database migrations
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── run.py
```

## Database Migrations

Schema changes are managed with Flask-Migrate (Alembic):

```bash
# Apply migrations (runs automatically on container start)
flask db upgrade

# Generate a new migration after model changes
flask db migrate -m "Description"

# Existing databases: stamp to current version first
flask db stamp head
```

## Upgrading

### From v1.0.x to v1.2.0

1. Pull latest code
2. Rebuild container: `docker compose build`
3. For existing databases, stamp the migration head:
   ```bash
   docker compose exec video-downloader flask db stamp head
   ```
4. Restart: `docker compose up -d`

New columns (`audio_only`, `clip_start`, `clip_end`) are added automatically via `db.create_all()` for SQLite databases.

## License

MIT License
