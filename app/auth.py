from flask import Blueprint, render_template, redirect, url_for, flash, request, session, make_response, current_app
from flask_login import login_user, logout_user, login_required, current_user
import logging
from app import db
from app.models import User
import time
from app.security.jwt_helpers import issue_token

# --- Blueprint Setup ---
auth = Blueprint('auth', __name__)

# --- LOGIN ROUTE ---
# All geo-filtering logic has been removed from this file. It is now handled
# globally by the middleware registered in app/__init__.py.
@auth.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect them to the dashboard.
    """
    Enforce 3 factors:
      1) username exists
      2) password matches
      3) OTP (from email) matches, belongs to the same user, and is not expired
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Handle the form submission
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        otp_input = request.form.get('totp', '').strip()

        # --- Step 1: user must exist ---
        user = User.query.filter_by(username=username).first()

        if not user:
            flash('User not found')
            return render_template('login.html', prev_username=username)

        # --- Step 2: password must match ---
        if not password or not user.check_password(password):
            flash('Invalid password')
            
            # Get user's IP for logging failed attempts, as it's still useful.
            forwarded_for = request.headers.get('X-Forwarded-For')
            user_ip = forwarded_for.split(',')[0].strip() if forwarded_for else request.remote_addr
            logging.warning(f"Failed login attempt for username: '{username}' from IP: {user_ip}")
            
            return render_template('login.html', prev_username=username)
          

        # Check if MFA is enabled
        if not current_app.config.get('ENABLE_MFA', False):
            # Skip OTP, directly log in
            login_user(user)

            # issue JWT session token and set as secure HttpOnly cookie
            token = issue_token(user.id)
            resp = make_response(redirect(request.args.get('next') or url_for('main.dashboard')))
            # cookie settings mirror app config but allow override via env
            secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
            samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
            resp.set_cookie('session_token', token, httponly=True, secure=secure, samesite=samesite)
                
            return resp

        # --- Step 3: OTP checks ---
        sess_code = session.get('otp_code')
        sess_user = session.get('otp_user')
        expires_at = session.get('otp_expires_at')   # set in /send-otp

        if not (sess_code and sess_user and expires_at):
            flash('OTP not requested or expired. Please click "Get OTP" first.')
            return render_template('login.html', prev_username=username)

        if sess_user != user.id or time.time() > float(expires_at):
            # clear when expired or bound to another user
            for k in ('otp_code', 'otp_user', 'otp_expires_at', 'otp_attempts'):
                session.pop(k, None)
            flash('OTP expired. Please request a new OTP.')
            return render_template('login.html', prev_username=username)

        attempts = session.get('otp_attempts', 0)
        if attempts >= 5:
            flash('Too many OTP attempts. Please request a new OTP.')
            return render_template('login.html', prev_username=username)

        if not otp_input or otp_input != sess_code:
            session['otp_attempts'] = attempts + 1
            flash('Invalid OTP')
            return render_template('login.html', prev_username=username)

        # --- Success: clear OTP session and log in ---
        for k in ('otp_code', 'otp_user', 'otp_expires_at', 'otp_attempts'):
            session.pop(k, None)

        login_user(user)

        # issue JWT session token and set as secure HttpOnly cookie
        token = issue_token(user.id)
        resp = make_response(redirect(request.args.get('next') or url_for('main.dashboard')))
        # cookie settings mirror app config but allow override via env
        secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
        samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
        resp.set_cookie('session_token', token, httponly=True, secure=secure, samesite=samesite)
            
        return resp

    return render_template('login.html')


# --- LOGOUT ROUTE ---
@auth.route('/logout')
def logout():
    logout_user()
    flash('You have been successfully logged out.')
    # Clear the session completely
    session.clear()
    resp = make_response(redirect(url_for('auth.login')))
    resp.delete_cookie('otp_session')  # Clear Flask session cookie (OTP data)
    resp.delete_cookie('session_token')  # Clear JWT token cookie
    return resp
