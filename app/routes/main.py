from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import User, Candidate, Vote, Region
from datetime import datetime
import hashlib
from functools import wraps
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
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

# ----- routes -----
@main.route('/')
def index():
    return redirect(url_for('auth.login'))

@main.route('/dashboard')
@login_required
def dashboard():
    candidates = Candidate.query.all()
    return render_template('dashboard.html',
                           candidates=candidates,
                           user=current_user)

@main.route("/delegate")
@roles_required("delegate", "manager")
@login_required
def delegate_dashboard():
    # if you want to restrict delegates to their own region, set delegate_region accordingly
    delegate_region = getattr(current_user.enrolment, "region", None) if hasattr(current_user, "enrolment") else None

    # show candidates: either all (for manager) or only delegate's region
    if current_user.is_manager or not delegate_region:
        candidates = Candidate.query.order_by(Candidate.name.asc()).all()
    else:
        candidates = Candidate.query.filter_by(region_id=delegate_region.id).order_by(Candidate.name.asc()).all()

    regions = Region.query.order_by(Region.name.asc()).all()
    return render_template("delegates_dashboard.html",
                           candidates=candidates,
                           regions=regions,
                           delegate_region=delegate_region)

@main.route('/vote', methods=['POST'])
@login_required
def vote():
    # check if already voted first
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

    candidate = Candidate.query.get(candidate_id)
    if not candidate:
        flash("Invalid candidate selected.")
        return redirect(url_for("main.dashboard"))

    # must vote in own region
    if current_user.enrolment.region_id != candidate.region_id:
        flash("You can only vote for candidates in your region.")
        return redirect(url_for("main.dashboard"))

    # create vote
    v = Vote(
        user_id=current_user.id,
        candidate_id=candidate.id,
        position=candidate.position
    )
    
    # Create vote hash for integrity
    vote_data = f"{current_user.id}{candidate.id}{datetime.utcnow().timestamp()}"
    v.vote_hash = hashlib.sha256(vote_data.encode()).hexdigest()

    # Persist vote and user state in a transaction. If another concurrent
    # request already recorded a vote for this user, the unique constraint
    # on Vote.user_id will raise IntegrityError which we catch and handle.
    try:
        # TODO: re-implement an ATOMIC transaction here if it was removed
        # TODO: generally apply structure and patterns in a new security requirement

        # Mark user as voted
        current_user.has_voted = True
        db.session.add(v)

        # Mark user as voted before commit to keep app and DB in sync
        db.session.commit()
    except IntegrityError:
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
    
    # Basic vote counting
    votes = Vote.query.all()
    results = {}
    total_votes = len(votes)
    
    for vote in votes:
        candidate = Candidate.query.get(vote.candidate_id)
        if candidate.name not in results:
            results[candidate.name] = 0
        results[candidate.name] += 1
    
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