from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, session, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app.helpers import flash_once
from app import db
from app.models import Candidate, Region
from app.utils.auth_decorators import roles_required
from app.vote_service import cast_anonymous_vote, AlreadyVotedError

main = Blueprint('main', __name__)

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


@main.route('/profile')
@login_required
def profile():
    """Show the current user's profile and enrolment info."""
    enrolment = getattr(current_user, 'enrolment', None)
    return render_template('profile.html', enrolment=enrolment)


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
    from app.models import Election
    candidates = Candidate.query.order_by(Candidate.name.asc()).all()
    eligible = user_is_eligible_to_vote(current_user)

    # Check if an election is currently open
    active_election = Election.query.filter_by(status='open').first()
    election_open = active_election and active_election.is_open

    return render_template(
        'dashboard.html',
        candidates=candidates,
        user=current_user,
        eligible=eligible,
        election_open=election_open,
        active_election=active_election,
    )


@main.route("/delegate", strict_slashes=False)
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
    # Check there is an active election
    from app.models import Election
    active_election = Election.query.filter_by(status='open').first()
    if not active_election or not active_election.is_open:
        flash_once('No election is currently open for voting.', 'error')
        return redirect(url_for("main.dashboard"))

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

    # Cast vote with pessimistic row lock to prevent TOCTOU race condition
    try:
        cast_anonymous_vote(db, current_user, candidate)
    except AlreadyVotedError:
        flash_once('You have already voted.')
        return redirect(url_for('main.dashboard'))
    except IntegrityError:
        db.session.rollback()
        flash_once('You have already voted.')
        return redirect(url_for('main.dashboard'))

    flash_once('Vote cast successfully!')
    return redirect(url_for('main.dashboard'))

@main.route("/results")
@roles_required("manager")  # managers only
def results():
    if not current_user.is_manager:
        flash_once('Access denied')
        return redirect(url_for('main.dashboard'))

    from app.services.results_service import get_vote_tallies
    from datetime import datetime, timezone

    votes = get_vote_tallies()
    total_votes = sum(votes.values())

    return render_template(
        'results.html',
        votes=votes,
        total_votes=total_votes,
        timestamp=datetime.now(timezone.utc),
        admin_user=current_user.username
    )

@main.errorhandler(403)
def forbidden(_):
    flash_once("Access denied")
    return redirect(url_for("main.dashboard"))