# app/routes/admin_users.py
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import User
from app import db
from functools import wraps

admin_bp = Blueprint('admin_users', __name__, url_prefix="/admin")

def admin_only(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash("Access denied: Admin only.")
            return redirect(url_for("main.dashboard"))
        return fn(*args, **kwargs)
    return wrapped

@admin_bp.route("/users")
@login_required
@admin_only
def manage_users():
    pending   = User.query.filter_by(account_status="pending").all()
    approved  = User.query.filter_by(account_status="approved").all()
    # normalize to 'rejected' (handlers set 'rejected')
    rejected  = User.query.filter_by(account_status="rejected").all()
    return render_template("admin_users.html",
                           pending_users=pending,
                           approved_users=approved,
                           rejected_users=rejected)

@admin_bp.route("/users/approve/<int:user_id>", methods=["POST"])
@login_required
@admin_only
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.account_status = "approved"
    # Backwards-compatible: some code refers to user.status; set it too.
    user.status = "active"
    # If the user has an electoral roll entry, mark it active and verified so
    # the user becomes eligible to vote after admin approval.
    enrol = getattr(user, 'enrolment', None)
    if enrol:
        enrol.status = 'active'
        enrol.verified = True
    db.session.commit()
    flash(f"✅ User '{user.username}' approved.")
    return redirect(url_for("admin_users.manage_users"))

@admin_bp.route("/users/reject/<int:user_id>", methods=["POST"])
@login_required
@admin_only
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    user.account_status = "rejected"
    user.status = "rejected"
    db.session.commit()
    flash(f"❌ User '{user.username}' rejected.")
    return redirect(url_for("admin_users.manage_users"))
