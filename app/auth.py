from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, session, make_response, current_app,g
)
from flask_login import login_user, logout_user, current_user
import logging

import re

from app import db
from app.models import User, Role, Region, ElectoralRoll
import time
from app.security.jwt_helpers import issue_token

# --- Blueprint Setup ---
auth = Blueprint('auth', __name__)

# -----------------------------
# Inline validators (demo-friendly)
# -----------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE    = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def is_strong_password(pw: str) -> bool:
    """
    Password policy for registration:
      - At least 8 characters
      - Must contain both letters and digits
    """
    if not pw or len(pw) < 8:
        return False
    has_letter = any(c.isalpha() for c in pw)
    has_digit  = any(c.isdigit() for c in pw)
    return has_letter and has_digit

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
        "VIC": "VIC east",  # change to your actual seeded region name if needed
        "QLD": "NSW",
        "SA":  "SA",
        "WA":  "NSW",
        "TAS": "NSW",
        "ACT": "NSW",
        "NT":  "NSW",
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

            # role-based redirect
            if user.is_manager:
                dashboard_url = url_for('dev.dev_dashboard')  # manager dashboard
            elif user.is_delegate:
                dashboard_url = url_for('main.delegate_dashboard')
            else:
                dashboard_url = url_for('main.dashboard')

            # gentle notice if not admin-approved yet
            if not getattr(user, "is_approved", False):
                flash("Your account is pending admin approval. You may not be eligible to vote yet.")

            resp = make_response(redirect(request.args.get('next') or dashboard_url))
            secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
            samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
            resp.set_cookie('session_token', token, httponly=True, secure=secure, samesite=samesite)
                
            return resp

        # 3) OTP checks (when MFA enabled)
        sess_code   = session.get('otp_code')
        sess_user   = session.get('otp_user')
        expires_at  = session.get('otp_expires_at')   # set in /send-otp

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
        token = issue_token(user.id)
        if not getattr(user, "is_approved", False):
            flash("Your account is pending admin approval. You may not be eligible to vote yet.")

        resp = make_response(redirect(request.args.get('next') or url_for('main.dashboard')))
        # cookie settings mirror app config but allow override via env
        secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
        samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
        resp.set_cookie('session_token', token, httponly=True, secure=secure, samesite=samesite)
            
        return resp

    return render_template('login.html')


# ------------------------------------------------------------
# REGISTER (admin approval flow)
# ------------------------------------------------------------
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
                flash("Selected state does not match the detected location from your IP address. If you are using a VPN or the detection failed, contact an administrator for support.")
                return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)


        # Username
        if not USERNAME_RE.fullmatch(username):
            flash("Username must be 3-32 chars (letters, digits, _.-)")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if User.query.filter_by(username=username).first():
            flash("Username already taken")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Email
        if not EMAIL_RE.fullmatch(email):
            flash("Invalid email format")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if User.query.filter_by(email=email).first():
            flash("Email already registered")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Password
        if password != confirm:
            flash("Passwords do not match")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if not is_strong_password(password):
            flash("Password too weak: must be 8+ chars with letters and digits")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        # Driver licence
        if not validate_driver_lic(lic_no, lic_state or None):
            flash("Invalid driver licence number")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)
        if User.query.filter_by(driver_lic_no=lic_no).first():
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
            flash(f"Failed to create user: {e}")
            return render_template('register.html', prev_username=username, prev_email=email, prev_state=lic_state)

        flash("Registration submitted. Waiting for admin approval.")
        return redirect(url_for('auth.login'))

    return render_template('register.html')


# ------------------------------------------------------------
# LOGOUT
# ------------------------------------------------------------
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
