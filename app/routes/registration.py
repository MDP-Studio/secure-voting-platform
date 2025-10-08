from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from app import db
from app.models import User, Role

registration = Blueprint('registration', __name__)

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
            flash('All fields are required')
            return redirect(url_for('registration.register'))

        # check if username/email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already taken')
            return redirect(url_for('registration.register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('registration.register'))

        # assign default role = voter
        voter_role = Role.query.filter_by(name="voter").first()
        if not voter_role:
            flash("Voter role not found in the system. Please seed roles first.")
            return redirect(url_for('registration.register'))

        # create user
        user = User()
        user.username = username
        user.email = email
        user.role_id = voter_role.id
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please log in.")
        return redirect(url_for('auth.login'))

    return render_template('register.html')