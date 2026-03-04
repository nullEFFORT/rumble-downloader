"""Video Downloader Flask application."""

import os
import logging
from flask import Flask
from .models import db
from .routes import bp
from .scheduler import DownloadScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def create_app(config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Default configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        'sqlite:////data/videodownloader.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['DOWNLOAD_PATH'] = os.environ.get('DOWNLOAD_PATH', '/downloads')

    # Apply custom config
    if config:
        app.config.update(config)

    # Initialize database
    db.init_app(app)

    # Create tables
    with app.app_context():
        db.create_all()

    # Register routes
    app.register_blueprint(bp)

    # Initialize and start scheduler
    scheduler = DownloadScheduler(download_path=app.config['DOWNLOAD_PATH'])
    scheduler.init_app(app)
    app.config['scheduler'] = scheduler
    scheduler.start()

    return app
