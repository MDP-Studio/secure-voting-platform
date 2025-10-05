from flask import Blueprint, render_template, redirect, url_for, flash, request, make_response, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User

from app.security.jwt_helpers import issue_token

auth = Blueprint('auth', __name__)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            # keep Flask-Login behavior for session-based endpoints if needed
            login_user(user)

            # issue JWT session token and set as secure HttpOnly cookie
            token = issue_token(user.id)
            resp = make_response(redirect(request.args.get('next') or url_for('main.dashboard')))
            # cookie settings mirror app config but allow override via env
            secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
            samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
            resp.set_cookie('session_token', token, httponly=True, secure=secure, samesite=samesite)
            return resp
        else:
            flash('Invalid username or password')

    return render_template('login.html')


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    resp = make_response(redirect(url_for('auth.login')))
    resp.delete_cookie('session_token')
    return resp
