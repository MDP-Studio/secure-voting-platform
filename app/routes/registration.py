from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app import db, mail
from app.models import User, Role
from app.security.password_validator import validate_password_strength, PasswordValidationError
from flask_mail import Message

registration = Blueprint('registration', __name__)

VERIFY_TOKEN_MAX_AGE = 86400  # 24 hours


def _get_serializer():
    secret = current_app.config.get('SECRET_KEY') or current_app.secret_key
    return URLSafeTimedSerializer(secret, salt='email-verify')


def send_verification_email(user):
    """Send an email verification link to the user."""
    s = _get_serializer()
    token = s.dumps(user.email)
    verify_url = url_for('registration.verify_email', token=token, _external=True)

    try:
        msg = Message(
            subject='notAEC - Verify Your Email',
            recipients=[user.email],
            body=(
                f"Hello {user.username},\n\n"
                f"Please verify your email by clicking the link below (valid for 24 hours):\n"
                f"{verify_url}\n\n"
                f"If you did not create an account, please ignore this email.\n\n"
                f"— notAEC"
            ),
        )
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send verification email: {e}")
        return False


@registration.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        # Basic validation
        if not username or not email or not password:
            flash('All fields are required', 'error')
            return redirect(url_for('registration.register'))

        # Validate password strength
        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            flash(f'Password validation failed: {error_message}', 'error')
            return redirect(url_for('registration.register'))

        # check if username/email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already taken', 'error')
            return redirect(url_for('registration.register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('registration.register'))

        # assign default role = voter
        voter_role = Role.query.filter_by(name="voter").first()
        if not voter_role:
            flash("Voter role not found in the system. Please seed roles first.", 'error')
            return redirect(url_for('registration.register'))

        # create user
        try:
            user = User()
            user.username = username
            user.email = email
            user.role_id = voter_role.id
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            # Send verification email
            send_verification_email(user)

            flash("Registration successful! Please check your email to verify your account, then wait for admin approval.", 'success')
            return redirect(url_for('auth.login'))
        except PasswordValidationError as e:
            flash(f'Password validation failed: {str(e)}', 'error')
            db.session.rollback()
            return redirect(url_for('registration.register'))
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'error')
            db.session.rollback()
            return redirect(url_for('registration.register'))

    return render_template('register.html')


@registration.route('/verify-email/<token>')
def verify_email(token):
    """Verify the user's email address via a signed token."""
    s = _get_serializer()

    try:
        email = s.loads(token, max_age=VERIFY_TOKEN_MAX_AGE)
    except SignatureExpired:
        flash('Verification link has expired. Please register again.', 'error')
        return redirect(url_for('auth.login'))
    except BadSignature:
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
