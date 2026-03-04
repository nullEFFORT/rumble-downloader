"""Video Downloader Flask application."""

import os
import logging
import secrets
from flask import Flask
from flask_migrate import Migrate
from .models import db
from .auth import auth_bp, is_auth_enabled
from .routes import bp
from .scheduler import DownloadScheduler

migrate = Migrate()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def create_app(config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Default configuration
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        logging.getLogger(__name__).warning(
            'SECRET_KEY not set — generating a random key. '
            'Sessions will not persist across restarts. Set SECRET_KEY env var.'
        )
        secret_key = secrets.token_hex(32)
    app.config['SECRET_KEY'] = secret_key
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        'sqlite:////data/videodownloader.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['DOWNLOAD_PATH'] = os.environ.get('DOWNLOAD_PATH', '/downloads')

    # Session security
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'

    # Apply custom config
    if config:
        app.config.update(config)

    # Initialize database and migrations
    db.init_app(app)
    migrate.init_app(app, db)

    # Create tables (for fresh installs without migrations)
    with app.app_context():
        db.create_all()

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    # Register routes
    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)

    # Initialize and start scheduler
    scheduler = DownloadScheduler(download_path=app.config['DOWNLOAD_PATH'])
    scheduler.init_app(app)
    app.config['scheduler'] = scheduler
    scheduler.start()

    return app
