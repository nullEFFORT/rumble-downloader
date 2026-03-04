"""Optional authentication middleware for the Video Downloader."""

import os
import functools
import logging
from flask import request, session, redirect, url_for, render_template, flash, Blueprint

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Auth is optional — enabled only when AUTH_USERNAME and AUTH_PASSWORD are set
AUTH_USERNAME = os.environ.get('AUTH_USERNAME')
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD')


def is_auth_enabled() -> bool:
    """Check if authentication is configured."""
    return bool(AUTH_USERNAME and AUTH_PASSWORD)


def login_required(f):
    """Decorator to require login for a route."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not is_auth_enabled():
            return f(*args, **kwargs)
        if not session.get('authenticated'):
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if not is_auth_enabled():
        return redirect('/')

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if username == AUTH_USERNAME and password == AUTH_PASSWORD:
            session['authenticated'] = True
            logger.info(f'User logged in from {request.remote_addr}')
            next_url = request.args.get('next', '/')
            return redirect(next_url)
        else:
            logger.warning(f'Failed login attempt from {request.remote_addr}')
            flash('Invalid credentials', 'error')

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """Logout."""
    session.pop('authenticated', None)
    return redirect(url_for('auth.login'))
