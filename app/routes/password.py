"""
Password management routes for changing and resetting passwords.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.security.password_validator import validate_password_strength, PasswordValidationError

password_bp = Blueprint('password', __name__)


@password_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow authenticated users to change their password."""
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
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
        
        # Update password
        try:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('main.dashboard'))
        except PasswordValidationError as e:
            flash(f'Password validation failed: {str(e)}', 'error')
            db.session.rollback()
            return render_template('change_password.html')
        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'error')
            db.session.rollback()
            return render_template('change_password.html')
    
    return render_template('change_password.html')
