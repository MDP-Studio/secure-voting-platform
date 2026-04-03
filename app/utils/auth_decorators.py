from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import login_required, current_user


def roles_required(*allowed):
    """Restrict access to users with one of the specified roles."""
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.has_role(*allowed):
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def admin_only(fn):
    """Restrict access to managers (admin users)."""
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash("Access denied: Admin only.")
            return redirect(url_for("main.dashboard"))
        return fn(*args, **kwargs)
    return wrapped
