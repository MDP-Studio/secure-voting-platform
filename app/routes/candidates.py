from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Candidate, Region
from functools import wraps

candidates = Blueprint('candidates', __name__)

# ----- tiny helpers -----
def roles_required(*allowed):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.has_role(*allowed):
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

# candidate management for delegates and managers
@candidates.route("/candidates/new", methods=["POST"])
@roles_required("delegate", "manager")
def create_candidate():
    name = (request.form.get("name") or "").strip()
    party = (request.form.get("party") or "").strip()
    position = (request.form.get("position") or "").strip()
    region_id_raw = request.form.get("region_id")

    if not name or not position or not region_id_raw:
        flash("Name, position, and region are required.")
        return redirect(url_for("main.delegate_dashboard"))

    try:
        region_id = int(region_id_raw)
    except ValueError:
        flash("Invalid region.")
        return redirect(url_for("main.delegate_dashboard"))

    c = Candidate(name=name, party=party or None, position=position, region_id=region_id)
    db.session.add(c)
    db.session.commit()
    flash("Candidate created.")
    return redirect(url_for("main.delegate_dashboard"))

@candidates.route("/candidates/<int:candidate_id>/update", methods=["POST"])
@roles_required("delegate", "manager")
@login_required
def update_candidate(candidate_id):
    c = Candidate.query.get_or_404(candidate_id)

    # optional region guard for delegates
    # if current_user.is_delegate:
    #     enrol = getattr(current_user, "enrolment", None)
    #     if not enrol or enrol.region_id != c.region_id:
    #         flash("Delegates can only edit candidates in their region.")
    #         return redirect(url_for("main.delegate_dashboard"))

    # simple update (you can replace with a proper edit form later)
    name = request.form.get("name")
    if name is not None:
        c.name = name.strip()
    party = request.form.get("party")
    if party is not None:
        c.party = party.strip() or None
    position = request.form.get("position")
    if position is not None:
        c.position = position.strip()
    region_id_str = request.form.get("region_id")
    if region_id_str is not None:
        try:
            c.region_id = int(region_id_str)
        except ValueError:
            pass

    db.session.commit()
    flash("Candidate updated.")
    return redirect(url_for("main.delegate_dashboard"))

@candidates.route("/candidates/<int:candidate_id>/delete", methods=["POST"])
@roles_required("delegate", "manager")
@login_required
def delete_candidate(candidate_id):
    c = Candidate.query.get_or_404(candidate_id)

    # optional region guard for delegates
    # if current_user.is_delegate:
    #     enrol = getattr(current_user, "enrolment", None)
    #     if not enrol or enrol.region_id != c.region_id:
    #         flash("Delegates can only delete candidates in their region.")
    #         return redirect(url_for("main.delegate_dashboard"))

    db.session.delete(c)
    db.session.commit()
    flash("Candidate deleted.")
    return redirect(url_for("main.delegate_dashboard"))