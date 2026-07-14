import logging
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app import db, mail
from app.models import User
from flask_mail import Message
from app.utils.public_url import public_url_for

registration = Blueprint('registration', __name__)

VERIFY_TOKEN_MAX_AGE = 86400  # 24 hours


def _get_serializer():
    secret = current_app.config.get('SECRET_KEY') or current_app.secret_key
    return URLSafeTimedSerializer(secret, salt='email-verify')


def send_verification_email(user):
    """Send an email verification link to the user."""
    s = _get_serializer()
    token = s.dumps(user.email)
    verify_url = public_url_for('registration.verify_email', token=token)

    try:
        msg = Message(
            subject='SecureVote - Verify Your Email',
            recipients=[user.email],
            body=(
                f"Hello {user.username},\n\n"
                f"Please verify your email by clicking the link below (valid for 24 hours):\n"
                f"{verify_url}\n\n"
                f"If you did not create an account, please ignore this email.\n\n"
                f"— SecureVote"
            ),
        )
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send verification email: {e}")
        return False


@registration.route('/verify-email/<token>')
def verify_email(token):
    """Verify the user's email address via a signed token."""
    s = _get_serializer()

    try:
        email = s.loads(token, max_age=VERIFY_TOKEN_MAX_AGE)
    except SignatureExpired:
        logging.getLogger(__name__).debug("Handled exception in app/routes/registration.py", exc_info=True)
        flash(
            'Verification link has expired. Please request a new link.',
            'error',
        )
        return redirect(url_for('auth.login'))
    except BadSignature:
        logging.getLogger(__name__).debug("Handled exception in app/routes/registration.py", exc_info=True)
        flash('Invalid verification link.', 'error')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid verification link.', 'error')
        return redirect(url_for('auth.login'))

    if user.email_verified:
        flash('Email already verified. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    user.email_verified = True
    db.session.commit()

    flash('Email verified successfully! Your account is pending admin approval.', 'success')
    return redirect(url_for('auth.login'))


@registration.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    """Resend an ownership challenge without disclosing account existence."""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if email:
            user = User.query.filter_by(
                email=email,
                email_verified=False,
                account_status='pending',
            ).first()
            if user is not None:
                send_verification_email(user)
        flash(
            'If a pending unverified account exists for that address, a new '
            'verification link has been sent.',
            'success',
        )
        return redirect(url_for('auth.login'))
    return render_template('resend_verification.html')
