# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-03-04

### Added
- **Rumble embedJS API extractor** (#6): Direct API calls for faster Rumble metadata, bypasses Cloudflare
- **Optional authentication** (#7): Session-based login with `AUTH_USERNAME`/`AUTH_PASSWORD` env vars
- **Timestamp clipping** (#8): Download specific segments with start/end timestamps via `/api/videos/<id>/clip`
- **Discord notifications** (#9): Webhook alerts for downloads, new videos, and errors via `DISCORD_WEBHOOK_URL`
- **Audio-only mode** (#20): Per-channel MP3 extraction with FFmpegExtractAudio postprocessor
- **Database migrations**: Flask-Migrate/Alembic for safe schema upgrades
- New model columns: `Channel.audio_only`, `Video.clip_start`, `Video.clip_end`
- Audio-only toggle in channel settings UI
- Logout link in navbar when authenticated
- `/api/videos/<id>/clip` endpoint for timestamp clipping

### Changed
- Scheduler uses Rumble extractor for Rumble channels instead of yt-dlp
- Download pipeline passes `audio_only`, `clip_start`, `clip_end` through to downloader
- `docker-compose.yml` documents new env vars (auth, Discord, commented out by default)
- Dockerfile copies `migrations/` directory and runs `flask db upgrade` before gunicorn

## [1.1.0] - 2026-03-04

### Fixed
- **Duplicate scheduler** (#3): Changed gunicorn from 2 workers to 1 worker + 8 threads, added fcntl file lock
- **Scheduler startup race** (#4): Replaced `@app.before_request` hook with direct `scheduler.start()` in `create_app()`
- **Queue shows video ID** (#5): Active downloads now display video title instead of numeric ID
- **Cloudflare 403 blocks** (#19): Added `curl-cffi` with `impersonate: chrome` for TLS fingerprint bypass

## [1.0.0] - 2026-02-28

### Added
- Initial release
- YouTube and Rumble channel monitoring
- Smart clip detection and filtering
- Concurrent downloads with priority queue
- Web UI with real-time queue control
- SQLite database for video tracking
- Docker container with gunicorn
