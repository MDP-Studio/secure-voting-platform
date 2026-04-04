from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, session, make_response, current_app,g
)
from app.helpers import flash_once
from flask_login import login_user, logout_user, current_user
import logging

import re
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
try:
    from app.routes.metrics import login_nonce_failures, gotcha_triggers, turnstile_failures
except Exception:
    # metrics may not be available in some environments; degrade silently
    login_nonce_failures = gotcha_triggers = turnstile_failures = None

from werkzeug.security import generate_password_hash
from app import db
from app.models import User, Role, Region, ElectoralRoll
from app.security.password_validator import validate_password_strength, PasswordValidationError
import time
from app.security.jwt_helpers import issue_token

# --- Blueprint Setup ---
auth = Blueprint('auth', __name__)

# -----------------------------
# Inline validators (demo-friendly)
# -----------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE    = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _checksum11(s: str) -> int:
    """
    Demo checksum for driver licence:
      Map digits to 0-9, letters A-Z -> 10..35
      sum(value * position) % 11  (last character is the check)
    """
    val = 0
    for i, ch in enumerate(s[:-1], start=1):
        if ch.isdigit():
            v = ord(ch) - 48
        else:
            v = 10 + (ord(ch.upper()) - 65)
        val += v * i
    return val % 11

def validate_driver_lic(lic_no: str, state: str | None = None) -> bool:
    """
    Simplified driver's licence validation (demo-friendly):
      - 6..10 alphanumeric
      - last char is checksum:
          * if checksum == 10 -> last must be 'X'
          * else last must equal the checksum digit
      - optional AU state code filter
    """
    if not lic_no:
        return False
    lic = lic_no.strip().replace(" ", "")
    if not re.fullmatch(r"[A-Za-z0-9]{6,10}", lic):
        return False

    if state:
        if state.upper() not in {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}:
            return False

    chk = _checksum11(lic)
    last = lic[-1].upper()
    if chk == 10:
        return last == 'X'
    return last.isdigit() and int(last) == chk

def _map_state_to_region(state_code: str | None) -> Region | None:
    """
    Map AU state to a Region row seeded in DB. Adjust to your seeding data.
    """
    if not state_code:
        return None
    mapping = {
        "NSW": "Sydney",
        "VIC": "VIC east",
        "QLD": "QLD",
        "SA":  "SA",
        "WA":  "WA",
        "TAS": "TAS",
        "ACT": "ACT",
        "NT":  "NT",
    }
    name = mapping.get(state_code.upper())
    return Region.query.filter_by(name=name).first() if name else None


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
        # GOTCHA honeypot: bots often fill hidden fields. If populated, reject.
        gotcha = (request.form.get('gotcha') or '').strip()
        if gotcha:
            try:
                if gotcha_triggers:
                    gotcha_triggers.inc()
            except Exception:
                pass
            forwarded_for = request.headers.get('X-Forwarded-For')
            user_ip = forwarded_for.split(',')[0].strip() if forwarded_for else request.remote_addr
            ua = request.headers.get('User-Agent', '<unknown>')
            logging.warning(f"GOTCHA triggered: gotcha='{gotcha}' username='{request.form.get('username')}' ip={user_ip} ua={ua}")
            flash('Bot-like activity detected. If you are a human, please try again.')
            return render_template('login.html', prev_username=request.form.get('username'))

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        otp_input = request.form.get('totp', '').strip()

        # Skip security checks when in TESTING mode
        if not current_app.config.get('TESTING', False):
            # Require a short-lived JS-issued nonce to ensure the client executed page JS.
            # This raises the bar against direct curl/wget POSTs.
            login_nonce = request.form.get('login_nonce')
            if not login_nonce:
                try:
                    if login_nonce_failures:
                        login_nonce_failures.inc()
                except Exception:
                    pass
                flash('Human verification required. Please use the web login form in a browser.')
                return render_template('login.html', prev_username=username)

            try:
                s = URLSafeTimedSerializer(current_app.config.get('SECRET_KEY') or current_app.secret_key, salt='login-nonce')
                # nonce valid for 5 minutes
                nonce_value = s.loads(login_nonce, max_age=300)
                # optional: ensure nonce_value contains expected structure; we used random hex
                if not isinstance(nonce_value, str):
                    raise BadSignature('invalid nonce')
            except SignatureExpired:
                try:
                    if login_nonce_failures:
                        login_nonce_failures.inc()
                except Exception:
                    pass
                flash('Human verification expired. Please reload the login page and try again.')
                return render_template('login.html', prev_username=username)
            except BadSignature:
                try:
                    if login_nonce_failures:
                        login_nonce_failures.inc()
                except Exception:
                    pass
                flash('Human verification failed. Please use the web login form in a browser.')
                return render_template('login.html', prev_username=username)

            # --- Step 0.5: Cloudflare Turnstile verification (optional) ---
            cf_secret = current_app.config.get('CF_TURNSTILE_SECRET')
            # If Turnstile is not configured, apply stricter server-side heuristics
            # to block naive command-line requests (curl/wget/httpie/requests).
            if not cf_secret:
                ua = (request.headers.get('User-Agent') or '').lower()
                # obvious CLI/HTTP libraries to block
                cli_signatures = ['curl', 'wget', 'httpie', 'powershell', 'python-requests', 'httpx']
                if any(sig in ua for sig in cli_signatures):
                    # Quick block for obvious CLI clients; instruct user to use a browser
                    flash('Please use a web browser to log in (command-line clients are blocked for security).')
                    return render_template('login.html', prev_username=username)

                # Require a Origin or Referer header for POSTs when no Turnstile is present.
                origin = request.headers.get('Origin') or request.headers.get('Referer')
                if not origin:
                    flash('Human verification required. Please use the web login form in a browser.')
                    return render_template('login.html', prev_username=username)
            if cf_secret:
                cf_token = request.form.get('cf-turnstile-response') or request.form.get('cf-turnstile-response-0')
                if not cf_token:
                    flash('Human verification failed. Please complete the Turnstile check.')
                    return render_template('login.html', prev_username=username)
                try:
                    import requests
                    resp = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify', data={
                        'secret': cf_secret,
                        'response': cf_token,
                        'remoteip': request.remote_addr,
                    }, timeout=5)
                    j = resp.json()
                    if not j.get('success'):
                        try:
                            if turnstile_failures:
                                turnstile_failures.inc()
                        except Exception:
                            pass
                        current_app.logger.warning('Turnstile verification failed: %s', j)
                        flash('Human verification failed. Please try again.')
                        return render_template('login.html', prev_username=username)
                except Exception as e:
                    try:
                        if turnstile_failures:
                            turnstile_failures.inc()
                    except Exception:
                        pass
                    current_app.logger.error('Turnstile verification error: %s', e)
                    flash('Human verification failed (service error). Please try again later.')
                    return render_template('login.html', prev_username=username)

        # --- Step 1: user must exist ---
        user = User.query.filter_by(username=username).first()

        if not user:
            # Don't reveal whether the username exists. Log internally but show
            # a generic error to the client to prevent user enumeration.
            logging.warning(f"Failed login attempt for unknown username: '{username}'")
            # Perform a dummy password hash so the response time is identical
            # to a real user with a wrong password. This avoids both the timing
            # side-channel and the DoS vector of thread-blocking sleeps.
            generate_password_hash("dummy-password-constant-time-equalization")
            flash_once('Invalid username or password')
            return render_template('login.html', prev_username=username)
        
        # --- Check if account is locked ---
        if user.is_account_locked():
            flash('Account is locked due to multiple failed login attempts. Please try again later or contact support.')
            logging.warning(f"Login attempt on locked account: '{username}'")
            return render_template('login.html', prev_username=username)

        # --- Step 2: password must match ---
        if not password or not user.check_password(password):
            # Generic message — don't leak whether user exists or password was wrong.
            forwarded_for = request.headers.get('X-Forwarded-For')
            user_ip = forwarded_for.split(',')[0].strip() if forwarded_for else request.remote_addr
            logging.warning(f"Failed login attempt for username: '{username}' from IP: {user_ip}")
            # No sleep — the password hash computation already provides constant-time behavior.
            user.record_failed_login()
            db.session.commit()

            flash_once('Invalid username or password')

            if user.is_account_locked():
                flash('Account has been locked due to multiple failed login attempts. Please try again in 30 minutes or contact support.', 'error')

            return render_template('login.html', prev_username=username)
          

        # --- MFA gate: if enabled, redirect to OTP verification page ---
        if current_app.config.get('ENABLE_MFA', False):
            # Store the authenticated user ID in session for the OTP step.
            # The user is NOT logged in yet — they must pass OTP first.
            session['mfa_pending_user_id'] = user.id
            session['mfa_pending_next'] = request.args.get('next', '')

            # Auto-send OTP email
            try:
                import random, string
                code = ''.join(random.choices(string.digits, k=6))
                session['otp_code'] = code
                session['otp_user'] = user.id
                session['otp_expires_at'] = time.time() + 300
                session['otp_attempts'] = 0

                from flask_mail import Message
                from app import mail
                msg = Message(
                    subject="SecureVote — Verification Code",
                    recipients=[user.email],
                    body=(
                        f"Your one-time verification code is: {code}\n\n"
                        f"This code expires in 5 minutes. Do not share it.\n\n"
                        f"— SecureVote Security"
                    ),
                )
                mail.send(msg)
            except Exception as e:
                current_app.logger.error(f"Failed to send MFA OTP: {e}")

            return redirect(url_for('auth.verify_mfa'))

        # --- No MFA: complete login directly ---
        return _complete_login(user, request.args.get('next'))

    # GET request — render the login form
    return render_template('login.html')


def _complete_login(user, next_url=None):
    """Finalize login: reset attempts, check password expiry, issue JWT."""
    user.reset_failed_logins()
    db.session.commit()

    if user.is_password_expired():
        flash('Your password has expired. Please change it to continue.', 'warning')
        login_user(user)
        return redirect(url_for('password.change_password'))

    login_user(user)
    token = issue_token(user.id)

    # Role-based redirect
    if user.is_manager:
        dashboard_url = url_for('dev.dev_dashboard')
    elif user.is_delegate:
        dashboard_url = url_for('main.delegate_dashboard')
    else:
        dashboard_url = url_for('main.dashboard')

    resp = make_response(redirect(next_url or dashboard_url))
    secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
    samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
    resp.set_cookie('session_token', token, httponly=True, secure=secure, samesite=samesite)
    return resp


@auth.route('/verify-mfa', methods=['GET', 'POST'])
def verify_mfa():
    """
    Step 2 of login: OTP verification page.
    Only accessible after successful password authentication.
    """
    pending_user_id = session.get('mfa_pending_user_id')
    if not pending_user_id:
        flash('Please sign in first.', 'error')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, pending_user_id)
    if not user:
        session.pop('mfa_pending_user_id', None)
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        otp_input = request.form.get('otp', '').strip()
        sess_code = session.get('otp_code')
        sess_user = session.get('otp_user')
        expires_at = session.get('otp_expires_at')

        if not (sess_code and sess_user and expires_at):
            flash('Verification code expired. Please sign in again.', 'error')
            session.pop('mfa_pending_user_id', None)
            return redirect(url_for('auth.login'))

        if sess_user != user.id or time.time() > float(expires_at):
            for k in ('otp_code', 'otp_user', 'otp_expires_at', 'otp_attempts', 'mfa_pending_user_id'):
                session.pop(k, None)
            flash('Verification code expired. Please sign in again.', 'error')
            return redirect(url_for('auth.login'))

        attempts = session.get('otp_attempts', 0)
        if attempts >= 5:
            for k in ('otp_code', 'otp_user', 'otp_expires_at', 'otp_attempts', 'mfa_pending_user_id'):
                session.pop(k, None)
            flash('Too many attempts. Please sign in again.', 'error')
            return redirect(url_for('auth.login'))

        if not otp_input or otp_input != sess_code:
            session['otp_attempts'] = attempts + 1
            flash('Invalid verification code.', 'error')
            return render_template('verify_mfa.html', email=user.email)

        # OTP valid — clear session and complete login
        next_url = session.get('mfa_pending_next', '')
        for k in ('otp_code', 'otp_user', 'otp_expires_at', 'otp_attempts', 'mfa_pending_user_id', 'mfa_pending_next'):
            session.pop(k, None)

        return _complete_login(user, next_url or None)

    return render_template('verify_mfa.html', email=user.email)


@auth.route('/login-nonce', methods=['GET'])
def login_nonce():
    """Return a short-lived signed nonce for login JS to embed in the form.

    The endpoint is safe to call from browser JS (no auth) and issues a
    signed random value valid for a short time (5 minutes).
    """
    s = URLSafeTimedSerializer(current_app.config.get('SECRET_KEY') or current_app.secret_key, salt='login-nonce')
    import secrets
    token = s.dumps(secrets.token_hex(16))
    return { 'nonce': token }


# ------------------------------------------------------------
# REGISTER (admin approval flow)
# ------------------------------------------------------------
# TODO: move this into its own file
@auth.route('/register', methods=['GET', 'POST'])
def register():
    """
    Registration with admin approval:
      - Validate username/email/password/licence
      - Default role = voter
      - User is created as 'pending'
      - Create ElectoralRoll as unverified/pending (admin will verify)
    Only username/email are echoed back on error; never echo passwords.
    """
    if request.method == 'POST':
        username   = (request.form.get('username') or '').strip()
        email      = (request.form.get('email') or '').strip().lower()
        password   = request.form.get('password') or ''
        confirm    = request.form.get('confirm') or ''
        lic_no     = (request.form.get('driver_lic_no') or '').strip()
        lic_state  = (request.form.get('driver_lic_state') or '').strip()
        
        # --- GEO CHECK: compare selected state to middleware-detected state ---
        # Middleware is expected to supply geo info in one of several places.
        # If no subdivision/state is available, skip the check but log it.
        detected_state = None

        # 1) flask.g (preferred if middleware attached there)
        if getattr(g, "geo_state", None):
            detected_state = g.geo_state
        # 2) common header names (middleware/proxy may set these)
        elif request.headers.get('X-GeoIP-Subdivision'):
            detected_state = request.headers.get('X-GeoIP-Subdivision')
        elif request.headers.get('X-GeoIP-State'):
            detected_state = request.headers.get('X-GeoIP-State')
        elif request.headers.get('X-Country-Subdivision'):
            detected_state = request.headers.get('X-Country-Subdivision')
        # 3) environ variable (some middleware sets GEOIP_* in environ)
        elif request.environ.get('GEOIP_SUBDIVISION'):
            detected_state = request.environ.get('GEOIP_SUBDIVISION')

        # Normalize detected state to standard AU codes where possible
        if detected_state:
            ds = detected_state.strip().upper()
            fullname_map = {
                "NEW SOUTH WALES": "NSW",
                "NSW": "NSW",
                "VICTORIA": "VIC",
                "VIC": "VIC",
                "QUEENSLAND": "QLD",
                "QLD": "QLD",
                "SOUTH AUSTRALIA": "SA",
                "SA": "SA",
                "WESTERN AUSTRALIA": "WA",
                "WA": "WA",
                "TASMANIA": "TAS",
                "TAS": "TAS",
                "NORTHERN TERRITORY": "NT",
                "NT": "NT",
                "AUSTRALIAN CAPITAL TERRITORY": "ACT",
                "ACT": "ACT",
            }
            detected_state_code = fullname_map.get(ds)
        else:
            detected_state_code = None
            logging.info("Geo-check: no subdivision/state available from middleware for registration attempt.")

        # If user supplied a licence state, compare against detected state code
        if lic_state:
            user_state_code = lic_state.strip().upper()
            if detected_state_code and user_state_code != detected_state_code:
                logging.warning(f"Registration geo-mismatch: user selected {user_state_code}, detected {detected_state_code} (IP).")
                flash_once("Selected state does not match the detected location from your IP address. If you are using a VPN or the detection failed, contact an administrator for support.")
                return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)


        # Username
        if not USERNAME_RE.fullmatch(username):
            flash_once("Username must be 3-32 chars (letters, digits, _.-)")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if User.query.filter_by(username=username).first():
            flash_once("Username already taken")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Email
        if not EMAIL_RE.fullmatch(email):
            flash_once("Invalid email format")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if User.query.filter_by(email=email).first():
            flash_once("Email already registered")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Password
        if password != confirm:
            flash_once("Passwords do not match")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        # Password validation has been centralized in validate_password_strength()
        # (replacing is_strong_password()) to ensure consistent password policy enforcement.
        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            flash(f"Password too weak: {error_message}")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Driver licence
        if not validate_driver_lic(lic_no, lic_state or None):
            flash_once("Invalid driver licence number")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if User.query.filter_by(driver_lic_no=lic_no).first():
            flash_once("Driver licence already bound to another account")
        # Uniqueness check via deterministic hash (since licence is stored encrypted)
        from app.models import _hash_lic
        lic_hash = _hash_lic(lic_no)
        if lic_hash and User.query.filter_by(driver_lic_hash=lic_hash).first():
            flash("Driver licence already bound to another account")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Ensure voter role exists
        voter_role = Role.query.filter_by(name="voter").first()
        if voter_role is None:
            voter_role = Role(name="voter", description="Can cast one vote")
            db.session.add(voter_role)
            db.session.flush()

        # 1) Create user as PENDING
        user = User(
            username=username,
            email=email,
            driver_lic_no=lic_no,
            driver_lic_state=lic_state.upper() if lic_state else None,
            role=voter_role,
            has_voted=False,
            account_status="pending",  # waiting for admin approval
        )
        # Ensure hash is set (event listeners will also do this, but set eagerly for safety)
        try:
            user.driver_lic_hash = lic_hash or _hash_lic(lic_no)
        except Exception:
            user.driver_lic_hash = _hash_lic(lic_no)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # need user.id for roll

        # 2) Create ElectoralRoll as unverified/pending (admin will verify)
        region = _map_state_to_region(user.driver_lic_state)
        roll = ElectoralRoll(
            roll_number=f"ER-{user.id:04d}",
            driver_license_number=user.driver_lic_no,
            full_name=user.username,              # demo placeholder
            date_of_birth=datetime(1995, 1, 1),   # demo placeholder
            address_line1="N/A",                  # demo placeholder
            suburb="N/A",
            state=(user.driver_lic_state or "N/A"),
            postcode="0000",
            region_id=(region.id if region else None),
            status="pending",     # not active yet
            verified=False,       # not verified yet
            verified_at=None,
            user_id=user.id,
        )
        db.session.add(roll)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash_once(f"Failed to create user: {e}")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # On success, notify user and redirect to login
        flash_once("Registration submitted. Waiting for admin approval.")
        return redirect(url_for('auth.login'))

    return render_template('register.html')


# ------------------------------------------------------------
# LOGOUT
# ------------------------------------------------------------
@auth.route('/logout')
def logout():
    logout_user()
    flash_once('You have been successfully logged out.')
    # Clear the session completely
    session.clear()
    resp = make_response(redirect(url_for('auth.login')))
    resp.delete_cookie('otp_session')  # Clear Flask session cookie (OTP data)
    resp.delete_cookie('session_token')  # Clear JWT token cookie
    return resp
