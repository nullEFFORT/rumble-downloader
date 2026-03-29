"""Flask routes for the web UI and API."""

import io
import json
import os
import xml.etree.ElementTree as ET
from flask import Blueprint, render_template, request, jsonify, current_app, send_file, abort, session, redirect, url_for
from .models import db, Channel, Video, DownloadLog
from .downloader import VideoDownloader
from .auth import is_auth_enabled

bp = Blueprint('main', __name__)


@bp.before_request
def check_auth():
    """Require login for all routes when auth is enabled."""
    if is_auth_enabled() and not session.get('authenticated'):
        # Allow health check endpoint without auth
        if request.endpoint == 'main.api_stats':
            return
        return redirect(url_for('auth.login', next=request.url))


@bp.route('/')
def index():
    """Main dashboard."""
    channels = Channel.query.order_by(Channel.name).all()
    stats = {
        'total_channels': Channel.query.count(),
        'enabled_channels': Channel.query.filter_by(enabled=True).count(),
        'total_videos': Video.query.count(),
        'pending_videos': Video.query.filter_by(status='pending').count(),
        'completed_videos': Video.query.filter_by(status='completed').count(),
        'failed_videos': Video.query.filter_by(status='failed').count(),
    }
    return render_template('index.html', channels=channels, stats=stats)


@bp.route('/channels')
def channels_list():
    """List all channels."""
    channels = Channel.query.order_by(Channel.name).all()
    return render_template('channels.html', channels=channels)


@bp.route('/channel/<int:channel_id>')
def channel_detail(channel_id):
    """Channel detail view."""
    channel = Channel.query.get_or_404(channel_id)
    videos = Video.query.filter_by(channel_id=channel_id)\
        .order_by(Video.discovered_at.desc()).limit(100).all()
    return render_template('channel_detail.html', channel=channel, videos=videos)


@bp.route('/videos')
def videos_list():
    """List all videos."""
    status = request.args.get('status', 'all')
    query = Video.query

    if status != 'all':
        query = query.filter_by(status=status)

    videos = query.order_by(Video.discovered_at.desc()).limit(200).all()
    return render_template('videos.html', videos=videos, status=status)


@bp.route('/logs')
def logs_list():
    """View download logs."""
    logs = DownloadLog.query.order_by(DownloadLog.created_at.desc()).limit(200).all()
    return render_template('logs.html', logs=logs)


# API Routes

@bp.route('/api/channels', methods=['GET'])
def api_channels():
    """Get all channels."""
    channels = Channel.query.all()
    return jsonify([c.to_dict() for c in channels])


@bp.route('/api/channels', methods=['POST'])
def api_add_channel():
    """Add a new channel from URL."""
    data = request.get_json()
    url = data.get('url')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # Check if channel already exists
    existing = Channel.query.filter_by(url=url).first()
    if existing:
        return jsonify({'error': 'Channel already exists', 'channel': existing.to_dict()}), 409

    # Extract channel info
    download_path = current_app.config.get('DOWNLOAD_PATH', '/downloads')
    downloader = VideoDownloader(download_path)
    info = downloader.extract_channel_info(url)

    if not info:
        return jsonify({'error': 'Could not extract channel info from URL'}), 400

    # Check if channel URL already exists (resolved URL might differ from input)
    channel_url = info.get('url') or url
    existing = Channel.query.filter_by(url=channel_url).first()
    if existing:
        return jsonify({'error': 'Channel already exists', 'channel': existing.to_dict()}), 409

    # Create channel
    channel = Channel(
        name=info.get('name', 'Unknown'),
        url=channel_url,
        platform=info.get('platform', 'unknown'),
        channel_id=info.get('channel_id'),
        rss_url=info.get('rss_url'),
        enabled=data.get('enabled', True),
        download_clips=data.get('download_clips', False),
        clip_threshold_seconds=data.get('clip_threshold_seconds', 300),
        backfill_enabled=data.get('backfill_enabled', False),
        backfill_limit=data.get('backfill_limit', 50),
        quality=data.get('quality', '1080'),
        audio_only=data.get('audio_only', False),
        check_interval_hours=data.get('check_interval_hours', 6),
    )

    db.session.add(channel)
    db.session.commit()

    return jsonify({
        'message': 'Channel added successfully',
        'channel': channel.to_dict(),
        'video_detected': info.get('video_title') is not None,
        'video_title': info.get('video_title'),
    }), 201


@bp.route('/api/channels/<int:channel_id>', methods=['GET'])
def api_get_channel(channel_id):
    """Get channel details."""
    channel = Channel.query.get_or_404(channel_id)
    return jsonify(channel.to_dict())


@bp.route('/api/channels/<int:channel_id>', methods=['PUT'])
def api_update_channel(channel_id):
    """Update channel settings."""
    channel = Channel.query.get_or_404(channel_id)
    data = request.get_json()

    # Update allowed fields
    for field in ['name', 'enabled', 'download_clips', 'clip_threshold_seconds',
                  'backfill_enabled', 'backfill_limit', 'quality', 'audio_only',
                  'check_interval_hours']:
        if field in data:
            setattr(channel, field, data[field])

    db.session.commit()
    return jsonify({'message': 'Channel updated', 'channel': channel.to_dict()})


@bp.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def api_delete_channel(channel_id):
    """Delete a channel."""
    channel = Channel.query.get_or_404(channel_id)
    db.session.delete(channel)
    db.session.commit()
    return jsonify({'message': 'Channel deleted'})


@bp.route('/api/channels/<int:channel_id>/check', methods=['POST'])
def api_check_channel(channel_id):
    """Trigger immediate channel check."""
    channel = Channel.query.get_or_404(channel_id)
    scheduler = current_app.config.get('scheduler')
    if scheduler:
        scheduler.check_channel_now(channel_id)
    return jsonify({'message': 'Channel check triggered'})


@bp.route('/api/channels/<int:channel_id>/backfill', methods=['POST'])
def api_backfill_channel(channel_id):
    """Trigger channel backfill."""
    channel = Channel.query.get_or_404(channel_id)
    scheduler = current_app.config.get('scheduler')
    if scheduler:
        scheduler.backfill_channel(channel_id)
    return jsonify({'message': 'Backfill triggered'})


@bp.route('/api/channels/discover', methods=['POST'])
def api_discover_channel():
    """Discover channel info from URL without adding it."""
    data = request.get_json()
    url = data.get('url')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    download_path = current_app.config.get('DOWNLOAD_PATH', '/downloads')
    downloader = VideoDownloader(download_path)
    info = downloader.extract_channel_info(url)

    if not info:
        return jsonify({'error': 'Could not extract channel info from URL'}), 400

    return jsonify({
        'name': info.get('name'),
        'url': info.get('url'),
        'platform': info.get('platform'),
        'channel_id': info.get('channel_id'),
        'rss_url': info.get('rss_url'),
        'thumbnail': info.get('thumbnail'),
        'video_detected': info.get('video_title') is not None,
        'video_title': info.get('video_title'),
    })


@bp.route('/api/videos', methods=['GET'])
def api_videos():
    """Get videos with optional filters."""
    channel_id = request.args.get('channel_id', type=int)
    status = request.args.get('status')
    is_clip = request.args.get('is_clip', type=bool)
    limit = min(request.args.get('limit', 100, type=int), 500)

    query = Video.query

    if channel_id:
        query = query.filter_by(channel_id=channel_id)
    if status:
        query = query.filter_by(status=status)
    if is_clip is not None:
        query = query.filter_by(is_clip=is_clip)

    videos = query.order_by(Video.discovered_at.desc()).limit(limit).all()
    return jsonify([v.to_dict() for v in videos])


@bp.route('/api/videos/<int:video_id>/download', methods=['POST'])
def api_download_video(video_id):
    """Trigger video download."""
    video = Video.query.get_or_404(video_id)

    if video.status not in ('pending', 'failed', 'skipped'):
        return jsonify({'error': f'Video is {video.status}'}), 400

    video.status = 'pending'
    db.session.commit()

    scheduler = current_app.config.get('scheduler')
    if scheduler:
        scheduler.download_video_now(video_id)

    return jsonify({'message': 'Download queued'})


@bp.route('/api/videos/<int:video_id>/skip', methods=['POST'])
def api_skip_video(video_id):
    """Mark video as skipped."""
    video = Video.query.get_or_404(video_id)
    video.status = 'skipped'
    db.session.commit()
    return jsonify({'message': 'Video skipped'})


@bp.route('/api/stats', methods=['GET'])
def api_stats():
    """Get download statistics."""
    return jsonify({
        'total_channels': Channel.query.count(),
        'enabled_channels': Channel.query.filter_by(enabled=True).count(),
        'total_videos': Video.query.count(),
        'pending_videos': Video.query.filter_by(status='pending').count(),
        'downloading_videos': Video.query.filter_by(status='downloading').count(),
        'completed_videos': Video.query.filter_by(status='completed').count(),
        'failed_videos': Video.query.filter_by(status='failed').count(),
        'skipped_videos': Video.query.filter_by(status='skipped').count(),
        'clips_detected': Video.query.filter_by(is_clip=True).count(),
    })


@bp.route('/api/logs', methods=['GET'])
def api_logs():
    """Get recent logs."""
    limit = min(request.args.get('limit', 100, type=int), 500)
    logs = DownloadLog.query.order_by(DownloadLog.created_at.desc()).limit(limit).all()
    return jsonify([{
        'id': log.id,
        'video_id': log.video_id,
        'channel_id': log.channel_id,
        'action': log.action,
        'message': log.message,
        'details': log.details,
        'created_at': log.created_at.isoformat(),
    } for log in logs])


# ==================== Queue Control API ====================

@bp.route('/api/queue/status', methods=['GET'])
def api_queue_status():
    """Get queue status including pause state and active downloads."""
    scheduler = current_app.config.get('scheduler')
    if not scheduler:
        return jsonify({'error': 'Scheduler not available'}), 500

    status = scheduler.get_queue_status()
    status['pending_count'] = Video.query.filter_by(status='pending').count()
    return jsonify(status)


@bp.route('/api/queue/pause', methods=['POST'])
def api_queue_pause():
    """Pause the download queue."""
    scheduler = current_app.config.get('scheduler')
    if not scheduler:
        return jsonify({'error': 'Scheduler not available'}), 500

    scheduler.pause_queue()
    return jsonify({'message': 'Queue paused', 'paused': True})


@bp.route('/api/queue/resume', methods=['POST'])
def api_queue_resume():
    """Resume the download queue."""
    scheduler = current_app.config.get('scheduler')
    if not scheduler:
        return jsonify({'error': 'Scheduler not available'}), 500

    scheduler.resume_queue()
    return jsonify({'message': 'Queue resumed', 'paused': False})


@bp.route('/api/queue/cancel-all', methods=['POST'])
def api_queue_cancel_all():
    """Cancel all active downloads."""
    scheduler = current_app.config.get('scheduler')
    if not scheduler:
        return jsonify({'error': 'Scheduler not available'}), 500

    scheduler.cancel_all_downloads()
    return jsonify({'message': 'Cancellation requested for all active downloads'})


@bp.route('/api/videos/<int:video_id>/cancel', methods=['POST'])
def api_cancel_video(video_id):
    """Cancel an active download."""
    scheduler = current_app.config.get('scheduler')
    if not scheduler:
        return jsonify({'error': 'Scheduler not available'}), 500

    if scheduler.cancel_download(video_id):
        return jsonify({'message': 'Cancellation requested'})
    else:
        return jsonify({'error': 'Video is not currently downloading'}), 400


@bp.route('/api/videos/<int:video_id>/priority', methods=['POST'])
def api_set_priority(video_id):
    """Set video download priority."""
    video = Video.query.get_or_404(video_id)
    data = request.get_json()
    priority = data.get('priority', 0)

    video.priority = priority
    db.session.commit()

    return jsonify({'message': 'Priority updated', 'video_id': video_id, 'priority': priority})


@bp.route('/api/videos/<int:video_id>/unskip', methods=['POST'])
def api_unskip_video(video_id):
    """Move a skipped video back to pending."""
    video = Video.query.get_or_404(video_id)

    if video.status != 'skipped':
        return jsonify({'error': f'Video is {video.status}, not skipped'}), 400

    video.status = 'pending'
    video.error_message = None
    db.session.commit()

    return jsonify({'message': 'Video moved to pending'})


@bp.route('/api/videos/bulk-skip', methods=['POST'])
def api_bulk_skip():
    """Skip multiple videos at once."""
    data = request.get_json()
    video_ids = data.get('video_ids', [])

    if not video_ids:
        return jsonify({'error': 'No video IDs provided'}), 400

    count = Video.query.filter(Video.id.in_(video_ids), Video.status == 'pending')\
        .update({Video.status: 'skipped'}, synchronize_session=False)
    db.session.commit()

    return jsonify({'message': f'Skipped {count} videos'})


@bp.route('/api/videos/bulk-priority', methods=['POST'])
def api_bulk_priority():
    """Set priority for multiple videos at once."""
    data = request.get_json()
    video_ids = data.get('video_ids', [])
    priority = data.get('priority', 0)

    if not video_ids:
        return jsonify({'error': 'No video IDs provided'}), 400

    count = Video.query.filter(Video.id.in_(video_ids))\
        .update({Video.priority: priority}, synchronize_session=False)
    db.session.commit()

    return jsonify({'message': f'Updated priority for {count} videos'})


def _validate_file_path(file_path):
    """Validate file_path is within DOWNLOAD_PATH to prevent path traversal."""
    download_path = current_app.config.get('DOWNLOAD_PATH', '/downloads')
    real_path = os.path.realpath(file_path)
    if not real_path.startswith(os.path.realpath(download_path) + os.sep):
        abort(403, description='Access denied')
    return real_path


@bp.route('/api/videos/<int:video_id>/play')
def api_play_video(video_id):
    """Stream the downloaded video file for playback."""
    video = Video.query.get_or_404(video_id)

    if not video.file_path:
        abort(404, description='No file path recorded for this video')

    real_path = _validate_file_path(video.file_path)

    if not os.path.exists(real_path):
        abort(404, description='Video file not found on disk')

    # Determine mimetype based on extension
    ext = os.path.splitext(real_path)[1].lower()
    mimetypes = {
        '.mp4': 'video/mp4',
        '.mp3': 'audio/mpeg',
        '.mkv': 'video/x-matroska',
        '.webm': 'video/webm',
        '.avi': 'video/x-msvideo',
        '.mov': 'video/quicktime',
    }
    mimetype = mimetypes.get(ext, 'video/mp4')

    return send_file(
        real_path,
        mimetype=mimetype,
        as_attachment=False,
        download_name=os.path.basename(real_path)
    )


@bp.route('/api/videos/<int:video_id>/delete-file', methods=['POST'])
def api_delete_video_file(video_id):
    """Delete the downloaded video file from disk."""
    video = Video.query.get_or_404(video_id)

    if not video.file_path:
        return jsonify({'error': 'No file path recorded for this video'}), 400

    real_path = _validate_file_path(video.file_path)

    if not os.path.exists(real_path):
        # File doesn't exist, just clear the database record
        video.file_path = None
        video.file_size = None
        video.status = 'pending'
        video.downloaded_at = None
        db.session.commit()
        return jsonify({'message': 'File not found, cleared record'})

    try:
        os.remove(real_path)
        video.file_path = None
        video.file_size = None
        video.status = 'pending'
        video.downloaded_at = None
        db.session.commit()
        return jsonify({'message': 'File deleted successfully'})
    except OSError as e:
        return jsonify({'error': f'Failed to delete file: {str(e)}'}), 500


@bp.route('/api/videos/<int:video_id>/open', methods=['GET'])
def api_get_video_open_url(video_id):
    """Get the URL or file path to open the video."""
    video = Video.query.get_or_404(video_id)

    if video.status == 'completed' and video.file_path:
        # Return the local file path for completed downloads
        return jsonify({
            'type': 'file',
            'path': video.file_path,
            'url': video.url
        })
    else:
        # Return the source URL for non-downloaded videos
        return jsonify({
            'type': 'url',
            'url': video.url
        })


@bp.route('/api/videos/<int:video_id>/clip', methods=['POST'])
def api_set_clip(video_id):
    """Set timestamp clipping for a video."""
    video = Video.query.get_or_404(video_id)
    data = request.get_json()

    video.clip_start = data.get('clip_start')
    video.clip_end = data.get('clip_end')
    db.session.commit()

    return jsonify({
        'message': 'Clip timestamps set',
        'clip_start': video.clip_start,
        'clip_end': video.clip_end,
    })


# ==================== Import / Export API ====================

@bp.route('/api/channels/export', methods=['GET'])
def api_channels_export():
    """Export all channels as JSON or OPML.

    Query params:
        format: 'json' (default) or 'opml'
    """
    fmt = request.args.get('format', 'json').lower()
    channels = Channel.query.order_by(Channel.name).all()

    if fmt == 'opml':
        # Build OPML XML document
        opml = ET.Element('opml', version='2.0')

        head = ET.SubElement(opml, 'head')
        title_el = ET.SubElement(head, 'title')
        title_el.text = 'Rumble Downloader Channel Subscriptions'

        body = ET.SubElement(opml, 'body')
        for ch in channels:
            attrs = {
                'text': ch.name,
                'type': 'rss',
                'xmlUrl': ch.url,
                'platform': ch.platform,
                'quality': ch.quality or '1080',
                'audio_only': 'true' if ch.audio_only else 'false',
                'download_clips': 'true' if ch.download_clips else 'false',
                'clip_threshold_seconds': str(ch.clip_threshold_seconds or 300),
                'check_interval_hours': str(ch.check_interval_hours or 6),
                'enabled': 'true' if ch.enabled else 'false',
                'backfill_limit': str(ch.backfill_limit or 50),
            }
            ET.SubElement(body, 'outline', **attrs)

        xml_bytes = ET.tostring(opml, encoding='unicode', xml_declaration=False)
        xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

        return current_app.response_class(
            xml_output,
            mimetype='text/x-opml',
            headers={
                'Content-Disposition': 'attachment; filename="channels.opml"',
            }
        )

    else:
        # JSON export — include all configurable settings
        export_data = []
        for ch in channels:
            export_data.append({
                'name': ch.name,
                'url': ch.url,
                'platform': ch.platform,
                'quality': ch.quality,
                'audio_only': ch.audio_only,
                'download_clips': ch.download_clips,
                'clip_threshold_seconds': ch.clip_threshold_seconds,
                'check_interval_hours': ch.check_interval_hours,
                'enabled': ch.enabled,
                'backfill_limit': ch.backfill_limit,
            })

        json_bytes = json.dumps(export_data, indent=2).encode('utf-8')
        return current_app.response_class(
            json_bytes,
            mimetype='application/json',
            headers={
                'Content-Disposition': 'attachment; filename="channels.json"',
            }
        )


@bp.route('/api/channels/import', methods=['POST'])
def api_channels_import():
    """Import channels from a JSON or OPML file upload.

    Accepts multipart/form-data with a 'file' field.
    Auto-detects format from file content.
    Skips channels whose URL already exists (duplicate detection).

    Returns a summary: imported, skipped, errors.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    upload = request.files['file']
    if not upload.filename:
        return jsonify({'error': 'Empty filename'}), 400

    try:
        raw = upload.read().decode('utf-8').strip()
    except UnicodeDecodeError:
        return jsonify({'error': 'File must be UTF-8 encoded text'}), 400

    # Auto-detect format: XML starts with '<', otherwise try JSON
    channels_data = []
    parse_errors = []

    if raw.startswith('<'):
        # Parse OPML
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            return jsonify({'error': f'Invalid XML: {exc}'}), 400

        body = root.find('body')
        if body is None:
            return jsonify({'error': 'OPML missing <body> element'}), 400

        for outline in body.findall('outline'):
            url = outline.get('xmlUrl') or outline.get('url')
            name = outline.get('text') or outline.get('title')
            if not url:
                parse_errors.append(f'Outline "{name or "unknown"}" missing xmlUrl, skipped')
                continue

            def _bool(val, default=False):
                if val is None:
                    return default
                return val.lower() == 'true'

            def _int(val, default=0):
                try:
                    return int(val) if val is not None else default
                except ValueError:
                    return default

            channels_data.append({
                'name': name or url,
                'url': url,
                'platform': outline.get('platform', 'rumble'),
                'quality': outline.get('quality', '1080'),
                'audio_only': _bool(outline.get('audio_only'), False),
                'download_clips': _bool(outline.get('download_clips'), False),
                'clip_threshold_seconds': _int(outline.get('clip_threshold_seconds'), 300),
                'check_interval_hours': _int(outline.get('check_interval_hours'), 6),
                'enabled': _bool(outline.get('enabled'), True),
                'backfill_limit': _int(outline.get('backfill_limit'), 50),
            })
    else:
        # Parse JSON
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return jsonify({'error': f'Invalid JSON: {exc}'}), 400

        if not isinstance(parsed, list):
            return jsonify({'error': 'JSON must be an array of channel objects'}), 400

        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                parse_errors.append(f'Item {i} is not an object, skipped')
                continue
            url = item.get('url')
            if not url:
                parse_errors.append(f'Item {i} missing url, skipped')
                continue
            channels_data.append({
                'name': item.get('name') or url,
                'url': url,
                'platform': item.get('platform', 'rumble'),
                'quality': item.get('quality', '1080'),
                'audio_only': bool(item.get('audio_only', False)),
                'download_clips': bool(item.get('download_clips', False)),
                'clip_threshold_seconds': int(item.get('clip_threshold_seconds', 300)),
                'check_interval_hours': int(item.get('check_interval_hours', 6)),
                'enabled': bool(item.get('enabled', True)),
                'backfill_limit': int(item.get('backfill_limit', 50)),
            })

    imported = 0
    skipped = 0
    import_errors = list(parse_errors)

    for entry in channels_data:
        existing = Channel.query.filter_by(url=entry['url']).first()
        if existing:
            skipped += 1
            continue
        try:
            channel = Channel(
                name=entry['name'],
                url=entry['url'],
                platform=entry['platform'],
                quality=entry['quality'],
                audio_only=entry['audio_only'],
                download_clips=entry['download_clips'],
                clip_threshold_seconds=entry['clip_threshold_seconds'],
                check_interval_hours=entry['check_interval_hours'],
                enabled=entry['enabled'],
                backfill_limit=entry['backfill_limit'],
            )
            db.session.add(channel)
            db.session.flush()  # catch constraint errors before commit
            imported += 1
        except Exception as exc:
            db.session.rollback()
            import_errors.append(f'Failed to import "{entry["name"]}": {exc}')
            continue

    db.session.commit()

    return jsonify({
        'imported': imported,
        'skipped': skipped,
        'errors': import_errors,
        'message': f'Import complete: {imported} imported, {skipped} skipped, {len(import_errors)} errors',
    })
