from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, session
from app.helpers import flash_once
from flask import Blueprint, jsonify, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Candidate, Region
from functools import wraps
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
    candidates = Candidate.query.order_by(Candidate.name.asc()).all()
    eligible = user_is_eligible_to_vote(current_user)

    # Eligibility details are shown directly in the template (avoid duplicating
    # these as flashed messages to prevent the same text showing twice).

    return render_template(
        'dashboard.html',
        candidates=candidates,
        user=current_user,
        eligible=eligible
    )


@main.route("/delegate/")
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
    # The Region model currently only has 'name', so list all regions.
    regions = Region.query.order_by(Region.name.asc()).all()
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
        flash_once("Your account is pending admin approval.")
        return redirect(url_for("main.dashboard"))

    if current_user.has_voted:
        flash_once('You have already voted.')
        return redirect(url_for("main.dashboard"))

    # only verified voters on the roll can vote
    if not user_is_eligible_to_vote(current_user):
        flash_once('You are not eligible to vote.')
        return redirect(url_for("main.dashboard")) # TODO: if the user can't vote they might not use the main dashboard for their login?

    candidate_id_raw = request.form.get("candidate_id")
    try:
        candidate_id = int(candidate_id_raw)
    except (TypeError, ValueError):
        flash_once('Invalid candidate selected.')
        return redirect(url_for("main.dashboard"))

    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        flash_once('Invalid candidate selected.')
        return redirect(url_for("main.dashboard"))

    # must vote in own region
    if current_user.enrolment.region_id != candidate.region_id:
        flash_once('You can only vote for candidates in your region.')
        return redirect(url_for("main.dashboard"))

    # Use a single atomic transaction via service: insert Ballot then Attendance
    try:
        cast_anonymous_vote(db, current_user, candidate)
    except IntegrityError:
        # Unique(election_id, voter_key) enforces one vote per person per election
        db.session.rollback()
        flash_once('You have already voted.')
        return redirect(url_for('main.dashboard'))
    
    #flash_once('Vote cast successfully!')
    return redirect(url_for('main.dashboard'))

@main.route("/results")
@roles_required("manager")  # managers only
def results():
    if not current_user.is_manager:
        flash_once('Access denied')
        return redirect(url_for('main.dashboard'))

    # Aggregate counts from the voters bind exclusively to avoid cross-bind JOINs.
    # We query using the voters engine directly via SQL, since Vote is bound
    # to 'voters' while Candidate may be accessed via 'admin' in this route.
    try:
        from sqlalchemy import text
        voters_engine = db.engines.get('voters')
        if voters_engine is None:
            raise RuntimeError("Voters engine not configured")
        with voters_engine.connect() as conn:
            # Prefer secure read-only surface via view; fallback to join if missing
            try:
                res = conn.execute(text(
                    """
                    SELECT name, votes
                    FROM vote_counts
                    ORDER BY votes DESC, name ASC
                    """
                ))
            except Exception:
                res = conn.execute(text(
                    """
                    SELECT c.name AS name, COUNT(v.id) AS votes
                    FROM candidate c
                    LEFT JOIN vote v ON v.candidate_id = c.id
                    GROUP BY c.id, c.name
                    ORDER BY votes DESC, c.name ASC
                    """
                ))
            rows = list(res)
        votes = {r[0]: int(r[1] or 0) for r in rows}
    except Exception as e:
        current_app.logger.warning(f"Failed to load results from voters bind: {e}")
        # Fallback: show zero counts for candidates from current bind
        votes = {c.name: 0 for c in Candidate.query.all()}

    total_votes = sum(votes.values())

    from datetime import datetime
    return render_template(
        'results.html',
        votes=votes,
        total_votes=total_votes,
        timestamp=datetime.utcnow(),
        admin_user=current_user.username
    )

@main.errorhandler(403)
def forbidden(_):
    flash_once("Access denied")
    return redirect(url_for("main.dashboard"))