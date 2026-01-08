"""Flask routes for the web UI and API."""

from flask import Blueprint, render_template, request, jsonify, current_app
from .models import db, Channel, Video, DownloadLog
from .downloader import VideoDownloader

bp = Blueprint('main', __name__)


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
                  'backfill_enabled', 'backfill_limit', 'quality', 'check_interval_hours']:
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
    limit = request.args.get('limit', 100, type=int)

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
    limit = request.args.get('limit', 100, type=int)
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
