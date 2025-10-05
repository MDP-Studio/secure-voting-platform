from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from .models import User
import logging

# --- Blueprint Setup ---
auth = Blueprint('auth', __name__)


# --- LOGIN ROUTE ---
# All geo-filtering logic has been removed from this file. It is now handled
# globally by the middleware registered in app/__init__.py.
@auth.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect them to the dashboard.
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Handle the form submission
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        # Verify the user exists and the password is correct.
        if user and user.check_password(password):
            login_user(user)
            # Redirect to the page the user was trying to access, or the dashboard.
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))
        else:
            # Get user's IP for logging failed attempts, as it's still useful.
            forwarded_for = request.headers.get('X-Forwarded-For')
            user_ip = forwarded_for.split(',')[0].strip() if forwarded_for else request.remote_addr
            logging.warning(f"Failed login attempt for username: '{username}' from IP: {user_ip}")
            flash('Invalid username or password.')
    
    return render_template('login.html')


# --- LOGOUT ROUTE ---
@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been successfully logged out.')
    return redirect(url_for('auth.login'))

# Note: The geo-filtering logic has been moved to middleware.py and is applied
# globally to all routes via app/__init__.py. This keeps the authentication
# code clean and focused on its primary purpose.