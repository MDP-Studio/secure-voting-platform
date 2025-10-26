from flask import Blueprint, jsonify, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import User, Candidate, Vote, Region, Ballot, Attendance
from datetime import datetime
import hashlib
from functools import wraps
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from flask import current_app
from app.vote_service import cast_anonymous_vote
main = Blueprint('main', __name__)

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

def user_is_eligible_to_vote(user):
    enrol = getattr(user, "enrolment", None)
    return (
        user.has_role("voter")
        and not user.has_voted
        and enrol is not None
        and enrol.status == "active"
        and enrol.verified
    )

# -----------------------------
# Routes
# -----------------------------
@main.route('/')
def index():
    """Landing redirects to login."""
    return redirect(url_for('auth.login'))


@main.route('/healthz')
def healthz():
    """Basic health check endpoint for load balancers and monitoring."""
    return jsonify(status="ok")


@main.route('/dashboard')
@login_required
def dashboard():
    """
    Dashboard shows candidates and eligibility messages.
    Template can use `eligible` to enable/disable vote UI.
    """
    # Show region-appropriate candidates for voters; show all for non-voters
    eligible = user_is_eligible_to_vote(current_user)
    enrol = getattr(current_user, "enrolment", None)
    if eligible and enrol is not None:
        candidates = (
            Candidate.query
            .filter(Candidate.region_id == enrol.region_id)
            .order_by(Candidate.name.asc())
            .all()
        )
    else:
        candidates = Candidate.query.order_by(Candidate.name.asc()).all()

    # Friendly hints for common non-eligible states (optional).
    # Keep flashes concise and specific; the template already shows a comprehensive
    # eligibility block, so avoid duplicating the generic "not eligible" message.
    if not getattr(current_user, "is_approved", False):
        flash("Your account is pending admin approval.")
    elif getattr(current_user, "enrolment", None) is None:
        flash("No enrolment found. Please contact support.")
    else:
        # Only surface very specific roll problems as flashes (status or verification)
        if current_user.enrolment.status != "active":
            flash(f"Electoral roll status: {current_user.enrolment.status} (requires active).")
        if not current_user.enrolment.verified:
            flash("Your electoral roll entry is not yet verified.")

    return render_template(
        'dashboard.html',
        candidates=candidates,
        user=current_user,
        eligible=eligible
    )


@main.route("/delegate")
@roles_required("delegate", "manager")  # roles_required already wraps login_required
def delegate_dashboard():
    """
    Delegates see candidates (optionally restricted to their region).
    Managers see all candidates.
    """
    delegate_region = getattr(getattr(current_user, "enrolment", None), "region", None)
    # Determine user's state from enrolment if available, otherwise from licence state
    enrol = getattr(current_user, "enrolment", None)
    user_state = None
    if enrol and getattr(enrol, "state", None):
        user_state = (enrol.state or "").upper()
    elif getattr(current_user, "driver_lic_state", None):
        user_state = (current_user.driver_lic_state or "").upper()

    if getattr(current_user, "is_manager", False) or not delegate_region:
        candidates = Candidate.query.order_by(Candidate.name.asc()).all()
    else:
        candidates = (
            Candidate.query
            .filter_by(region_id=delegate_region.id)
            .order_by(Candidate.name.asc())
            .all()
        )

    # Build region selection for delegates:
    # - Prefer district/upper items for the user's state if available
    # - Fallback to the list of states
    if user_state in ["ACT","NSW","NT","QLD","SA","TAS","VIC","WA"]:
        q = Region.query
        q = q.filter(
            db.and_(
                Region.state_code == user_state,
                Region.level.in_(["district", "upper"])  # show electoral areas
            )
        )
        regions = q.order_by(Region.name.asc()).all()
        if not regions:
            # fallback to showing state list if no detailed regions are seeded
            regions = (
                Region.query
                .filter(Region.level == "state")
                .order_by(Region.name.asc())
                .all()
            )
    else:
        regions = (
            Region.query
            .filter(Region.level == "state")
            .order_by(Region.name.asc())
            .all()
        )
    return render_template(
        "delegates_dashboard.html",
        candidates=candidates,
        regions=regions,
        delegate_region=delegate_region
    )


@main.route('/vote', methods=['POST'])
@login_required
def vote():
    """
    Records a single vote per user.
    - Enforces admin approval and eligibility.
    - Enforces one vote per user via DB unique constraint on Vote.user_id.
    """
    # Explicit approval gate (clear message)
    if not getattr(current_user, "is_approved", False):
        flash("Your account is pending admin approval.")
        return redirect(url_for("main.dashboard"))

    if current_user.has_voted:
        flash("You have already voted.")
        return redirect(url_for("main.dashboard"))

    # only verified voters on the roll can vote
    if not user_is_eligible_to_vote(current_user):
        flash("You are not eligible to vote.")
        return redirect(url_for("main.dashboard")) # TODO: if the user can't vote they might not use the main dashboard for their login?

    candidate_id_raw = request.form.get("candidate_id")
    try:
        candidate_id = int(candidate_id_raw)
    except (TypeError, ValueError):
        flash("Invalid candidate selected.")
        return redirect(url_for("main.dashboard"))

    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        flash("Invalid candidate selected.")
        return redirect(url_for("main.dashboard"))

    # must vote in own region
    if current_user.enrolment.region_id != candidate.region_id:
        flash("You can only vote for candidates in your region.")
        return redirect(url_for("main.dashboard"))

    # Use a single atomic transaction via service: insert Ballot then Attendance
    try:
        cast_anonymous_vote(db, current_user, candidate)
        # Persist changes immediately so the redirected dashboard reflects
        # the updated has_voted flag and the ballot/attendance rows exist.
        db.session.commit()
    except IntegrityError:
        # Unique(election_id, voter_key) enforces one vote per person per election
        db.session.rollback()
        flash('You have already voted.')
        return redirect(url_for('main.dashboard'))
    
    flash('Vote cast successfully!')
    return redirect(url_for('main.dashboard'))

@main.route("/results")
@roles_required("manager")  # managers only
def results():
    if not current_user.is_manager:
        flash('Access denied')
        return redirect(url_for('main.dashboard'))
    
    # Basic vote counting from anonymised ballots
    ballots = Ballot.query.all()
    results = {}
    total_votes = len(ballots)

    for ballot in ballots:
        candidate = db.session.get(Candidate, ballot.candidate_id)
        if not candidate:
            # Skip if candidate no longer exists
            continue
        results[candidate.name] = results.get(candidate.name, 0) + 1
    
    from datetime import datetime


    # TODO: Reimpement this
    """
        # aggregate with one query
    rows = (
        db.session.query(
            Candidate.name.label("name"),
            Candidate.position.label("position"),
            func.count(Vote.id).label("votes")
        )
        .join(Vote, Vote.candidate_id == Candidate.id, isouter=True)
        .group_by(Candidate.id)
        .order_by(func.count(Vote.id).desc(), Candidate.name.asc())
        .all()
    )
    # pass a simple list of dicts to the template
    results = [{"name": r.name, "position": r.position, "votes": int(r.votes or 0)} for r in rows]
    return render_template("results.html", results=results)
    
    """

    return render_template('results.html', 
                         votes=results, 
                         total_votes=total_votes,
                         timestamp=datetime.utcnow(),
                         admin_user=current_user.username)

@main.errorhandler(403)
def forbidden(_):
    flash("Access denied")
    return redirect(url_for("main.dashboard"))