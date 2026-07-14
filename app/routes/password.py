"""
Password management routes for changing and resetting passwords.
"""
import logging

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from app import db
from app.security.password_validator import validate_password_strength, PasswordValidationError

password_bp = Blueprint('password', __name__)


@password_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow authenticated users to change their password."""
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validate all fields are provided
        if not current_password or not new_password or not confirm_password:
            flash('All fields are required', 'error')
            return render_template('change_password.html')
        
        # Verify current password
        if not current_user.check_password(current_password):
            flash('Current password is incorrect', 'error')
            return render_template('change_password.html')
        
        # Check that new password is different from current
        if current_user.check_password(new_password):
            flash('New password must be different from current password', 'error')
            return render_template('change_password.html')
        
        # Validate new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return render_template('change_password.html')
        
        # Validate password strength
        is_valid, error_message = validate_password_strength(new_password)
        if not is_valid:
            flash(f'Password validation failed: {error_message}', 'error')
            return render_template('change_password.html')
        
        # Update password. Commit and token issuance are separate boundaries:
        # a token backend failure must not claim the committed password failed.
        try:
            current_user.set_password(new_password)
            db.session.commit()
        except PasswordValidationError as e:
            logging.getLogger(__name__).debug("Handled exception in app/routes/password.py", exc_info=True)
            flash(f'Password validation failed: {str(e)}', 'error')
            db.session.rollback()
            return render_template('change_password.html')
        except Exception:
            current_app.logger.exception("Password change transaction failed")
            db.session.rollback()
            flash('Password could not be changed. Please try again.', 'error')
            return render_template('change_password.html')

        try:
            from app.security.jwt_helpers import issue_token
            g._new_session_token = issue_token(
                current_user.id,
                current_user.session_version,
            )
        except Exception:
            current_app.logger.exception(
                "Password changed but replacement session issuance failed"
            )
            logout_user()
            g._clear_session_token = True
            flash(
                'Password changed successfully. Please sign in again.',
                'success',
            )
            return redirect(url_for('auth.login'))

        flash('Password changed successfully!', 'success')
        return redirect(url_for('main.dashboard'))
    
    return render_template('change_password.html')
