#!/usr/bin/env python3
"""Run the Video Downloader application."""

import os
from app import create_app

app = create_app()


def main():
    """Entry point for pipx/console_scripts."""
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')


if __name__ == '__main__':
    main()
