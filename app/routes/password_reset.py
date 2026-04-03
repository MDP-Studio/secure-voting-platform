"""
Password reset flow: forgot-password and reset-password routes.
Uses itsdangerous tokens sent via email for secure, time-limited resets.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app import db, mail
from app.models import User
from app.security.password_validator import validate_password_strength
from flask_mail import Message
from datetime import datetime, timezone

password_reset_bp = Blueprint('password_reset', __name__)

TOKEN_MAX_AGE = 1800  # 30 minutes


def _get_serializer():
    secret = current_app.config.get('SECRET_KEY') or current_app.secret_key
    return URLSafeTimedSerializer(secret, salt='password-reset')


def _send_reset_email(user):
    """Generate a reset token and send the reset email."""
    s = _get_serializer()
    token = s.dumps(user.email)

    reset_url = url_for('password_reset.reset_password', token=token, _external=True)

    try:
        msg = Message(
            subject='notAEC - Password Reset Request',
            recipients=[user.email],
            body=(
                f"Hello {user.username},\n\n"
                f"A password reset was requested for your notAEC account.\n\n"
                f"Click the link below to reset your password (valid for 30 minutes):\n"
                f"{reset_url}\n\n"
                f"If you did not request this, please ignore this email.\n\n"
                f"— notAEC Security"
            ),
        )
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send password reset email: {e}")
        return False


@password_reset_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()

        if email:
            user = User.query.filter_by(email=email).first()
            if user:
                _send_reset_email(user)

        # Always show the same message to prevent email enumeration
        flash('If an account with that email exists, a password reset link has been sent.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')


@password_reset_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    s = _get_serializer()

    try:
        email = s.loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        flash('This reset link has expired. Please request a new one.', 'error')
        return redirect(url_for('password_reset.forgot_password'))
    except BadSignature:
        flash('Invalid reset link.', 'error')
        return redirect(url_for('password_reset.forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid reset link.', 'error')
        return redirect(url_for('password_reset.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not new_password or not confirm_password:
            flash('All fields are required.', 'error')
            return render_template('reset_password.html', token=token)

        if new_password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', token=token)

        is_valid, error_message = validate_password_strength(new_password)
        if not is_valid:
            flash(f'Password too weak: {error_message}', 'error')
            return render_template('reset_password.html', token=token)

        user.set_password(new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        # Also unlock the account if it was locked
        user.failed_login_attempts = 0
        user.account_locked_until = None
        db.session.commit()

        flash('Your password has been reset. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)
