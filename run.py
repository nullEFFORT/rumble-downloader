#!/usr/bin/env python3
"""Run the Video Downloader application."""

from app import create_app

app = create_app()


def main():
    """Entry point for pipx/console_scripts."""
    app.run(host='0.0.0.0', port=5000, debug=True)


if __name__ == '__main__':
    main()
