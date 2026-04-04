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


# =====================================================================
# Blind Signature Voting Protocol
# =====================================================================

@main.route('/vote/blind-key')
def blind_signing_public_key():
    """Public endpoint: return RSA public key components for client-side blinding."""
    from app.security.blind_signature import get_public_key_components
    return jsonify(get_public_key_components(current_app.instance_path))


@main.route('/vote/request-token', methods=['POST'])
@login_required
def request_blind_token():
    """
    Phase 1 (authenticated): Sign a blinded ballot.

    The voter sends a blinded ballot and a nonce hash. The server:
    - Verifies eligibility (same checks as /vote)
    - Signs the blinded data WITHOUT seeing the ballot contents
    - Issues a VoteReceipt (double-vote prevention)
    - Returns the blind signature

    The server sees: blinded_ballot (random-looking int), nonce_hash.
    The server does NOT see: candidate_id, actual ballot.
    """
    from app.models import Election, User, VoteReceipt, BlindSignatureToken
    from app.security.blind_signature import blind_sign

    data = request.get_json(silent=True)
    if not data or 'blinded_ballot' not in data or 'nonce_hash' not in data:
        return jsonify({"error": "Missing blinded_ballot or nonce_hash"}), 400

    # Eligibility checks (same as /vote)
    active_election = Election.query.filter_by(status='open').first()
    if not active_election or not active_election.is_open:
        return jsonify({"error": "No election is currently open"}), 400

    if not getattr(current_user, "is_approved", False):
        return jsonify({"error": "Account pending approval"}), 403

    if not user_is_eligible_to_vote(current_user):
        return jsonify({"error": "Not eligible to vote"}), 403

    # Pessimistic lock on user row
    locked_user = (
        db.session.query(User)
        .filter(User.id == current_user.id)
        .with_for_update()
        .first()
    )
    if not locked_user or locked_user.has_voted:
        return jsonify({"error": "Already voted"}), 409

    try:
        blinded_int = int(data['blinded_ballot'], 16)
        nonce_hash = data['nonce_hash']
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid blinded_ballot format"}), 400

    # Issue receipt + token
    receipt = VoteReceipt(user_id=current_user.id)
    token = BlindSignatureToken(
        user_id=current_user.id,
        ballot_nonce_hash=nonce_hash,
    )
    db.session.add(receipt)
    db.session.add(token)
    locked_user.has_voted = True

    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Already voted"}), 409

    # Sign the blinded ballot
    blind_sig = blind_sign(blinded_int, current_app.instance_path)
    db.session.commit()

    return jsonify({"blind_signature": hex(blind_sig)})


@main.route('/vote/cast', methods=['POST'])
def cast_anonymous_ballot():
    """
    Phase 2 (anonymous): Submit an unblinded ballot + signature.

    NO authentication required. NO cookies sent (client uses credentials:'omit').
    The server verifies the signature proves the ballot was authorized by
    the blind-signing key, but CANNOT determine which voter submitted it.
    """
    import json as _json
    import secrets
    import hashlib
    from app.models import Vote, BlindSignatureToken
    from app.security.blind_signature import verify_unblinded_signature

    data = request.get_json(silent=True)
    if not data or 'ballot' not in data or 'signature' not in data:
        return jsonify({"error": "Missing ballot or signature"}), 400

    try:
        ballot_hex = data['ballot']
        ballot_bytes = bytes.fromhex(ballot_hex)
        ballot_json = _json.loads(ballot_bytes.decode('utf-8'))
        sig_int = int(data['signature'], 16)
    except (ValueError, TypeError, _json.JSONDecodeError):
        return jsonify({"error": "Invalid ballot or signature format"}), 400

    # Verify blind signature
    if not verify_unblinded_signature(ballot_bytes, sig_int, current_app.instance_path):
        return jsonify({"error": "Invalid signature"}), 403

    # Extract ballot fields
    candidate_id = ballot_json.get('candidate_id')
    nonce = ballot_json.get('nonce')
    if not candidate_id or not nonce:
        return jsonify({"error": "Malformed ballot"}), 400

    # Verify candidate exists
    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        return jsonify({"error": "Invalid candidate"}), 400

    # Replay prevention: find and redeem the token via nonce hash
    nonce_hash = hashlib.sha256(nonce.encode('utf-8')).hexdigest()
    token = BlindSignatureToken.query.filter_by(
        ballot_nonce_hash=nonce_hash,
        redeemed=False,
    ).first()
    if not token:
        return jsonify({"error": "Token already redeemed or invalid"}), 409

    from datetime import datetime, timezone
    token.redeemed = True
    token.redeemed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Store anonymous ballot
    ballot_nonce = secrets.token_hex(32)
    ts = datetime.now(timezone.utc).isoformat()
    vote_hash = hashlib.sha256(f"{ballot_nonce}:{candidate_id}:{ts}".encode()).hexdigest()

    vote = Vote(
        voter_token=ballot_nonce,
        candidate_id=candidate_id,
        position=candidate.position,
        vote_hash=vote_hash,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(vote)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Vote could not be recorded"}), 500

    return jsonify({"status": "ok", "message": "Your anonymous ballot has been recorded."})


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