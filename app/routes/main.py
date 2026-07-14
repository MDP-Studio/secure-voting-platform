import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, session, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app.helpers import flash_once
from app import db
from app.logging_service import record_audit_event
from app.models import BlindSignatureToken, Candidate, Region, VoteReceipt
from app.utils.auth_decorators import roles_required
from app.vote_service import IneligibleVoterError, lock_and_validate_voter

main = Blueprint('main', __name__)

def user_is_eligible_to_vote(user, election=None):
    """Return eligibility for the supplied election, not for the user's lifetime."""
    from app.models import BlindSignatureToken, VoteReceipt

    enrol = getattr(user, "enrolment", None)
    base_eligible = (
        user.is_approved
        and user.email_verified
        and user.has_role("voter")
        and enrol is not None
        and enrol.status == "active"
        and enrol.verified
    )
    if not base_eligible:
        return False
    if election is None:
        return True
    election_candidates = Candidate.query.filter_by(election_id=election.id).all()
    regions = {candidate.region_id for candidate in election_candidates}
    positions = {candidate.position for candidate in election_candidates}
    if (
        len(regions) != 1
        or len(positions) != 1
        or enrol.region_id not in regions
    ):
        return False
    has_direct_receipt = VoteReceipt.query.filter_by(
        user_id=user.id,
        election_id=election.id,
    ).first()
    has_blind_authorization = BlindSignatureToken.query.filter_by(
        user_id=user.id,
        election_id=election.id,
    ).first()
    return not (has_direct_receipt or has_blind_authorization)

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
    return render_template(
        'profile.html',
        enrolment=enrolment,
        election_participation_count=current_user.vote_receipts.count(),
    )


@main.route('/healthz')
def healthz():
    """Basic health check endpoint for load balancers and monitoring."""
    return jsonify(status="ok")


@main.route('/threat-model')
def threat_model():
    """Public, evidence-focused threat model summary."""
    return render_template('threat_model.html')


@main.route('/verification-ceremony')
def verification_ceremony():
    """Public, data-free rehearsal for independent result verification."""
    return render_template('verification_ceremony.html')


@main.route('/dashboard')
@login_required
def dashboard():
    """
    Dashboard shows candidates and eligibility messages.
    Template can use `eligible` to enable/disable vote UI.
    """
    from app.models import Election
    # Check if an election is currently open
    active_election = (
        Election.query.filter_by(status='open')
        .order_by(Election.open_at.desc(), Election.id.desc())
        .first()
    )
    election_open = bool(active_election and active_election.is_open)
    candidates = (
        Candidate.query.filter_by(election_id=active_election.id)
        .order_by(Candidate.name.asc())
        .all()
        if election_open
        else []
    )
    eligible = user_is_eligible_to_vote(current_user, active_election)
    election_regions = {candidate.region_id for candidate in candidates}
    election_positions = {candidate.position for candidate in candidates}
    election_roster_valid = len(election_regions) == 1 and len(election_positions) == 1
    election_region_match = bool(
        election_roster_valid
        and getattr(current_user, "enrolment", None)
        and current_user.enrolment.region_id in election_regions
    )
    has_voted_in_election = bool(
        active_election
        and VoteReceipt.query.filter_by(
            user_id=current_user.id,
            election_id=active_election.id,
        ).first()
    )
    has_ballot_authorization = bool(
        active_election
        and BlindSignatureToken.query.filter_by(
            user_id=current_user.id,
            election_id=active_election.id,
        ).first()
    )

    return render_template(
        'dashboard.html',
        candidates=candidates,
        user=current_user,
        eligible=eligible,
        election_open=election_open,
        active_election=active_election,
        has_voted_in_election=has_voted_in_election,
        has_ballot_authorization=has_ballot_authorization,
        election_roster_valid=election_roster_valid,
        election_region_match=election_region_match,
    )


@main.route("/delegate", strict_slashes=False)
@roles_required("delegate", "manager")  # roles_required already wraps login_required
def delegate_dashboard():
    """
    Delegates see candidates (optionally restricted to their region).
    Managers see all candidates.
    """
    from app.models import Election

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
        delegate_region=delegate_region,
        draft_elections=Election.query.filter_by(status="draft")
        .order_by(Election.created_at.desc())
        .all(),
    )


@main.route('/vote', methods=['POST'])
@login_required
def vote():
    """Reject the retired identity-linkable direct ballot submission path."""
    current_app.logger.warning(
        "Rejected a direct ballot submission; blind anonymous voting is required"
    )
    return jsonify(
        {
            "error": (
                "Direct ballot submission is disabled. "
                "Use the browser blind-ballot flow."
            )
        }
    ), 410


# =====================================================================
# Blind Signature Voting Protocol
# =====================================================================

@main.route('/vote/blind-key')
def blind_signing_public_key():
    """Return the immutable public key for one open election."""
    from app.models import Election
    from app.security.blind_signature import (
        BlindSigningKeyError,
        ensure_election_blind_signing_key,
    )

    raw_election_id = request.args.get("election_id")
    try:
        election_id = int(raw_election_id)
        if election_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        current_app.logger.debug("Rejected invalid election_id for blind key")
        return jsonify({"error": "A valid election_id is required"}), 400

    election = db.session.get(Election, election_id)
    if election is None:
        return jsonify({"error": "Election not found"}), 404
    if not election.is_open:
        return jsonify({"error": "Election is not open"}), 409

    try:
        components = ensure_election_blind_signing_key(
            current_app.instance_path,
            election.id,
            election.blind_signing_key_id,
        )
    except BlindSigningKeyError:
        current_app.logger.error(
            "The blind-signing key for election %s is unavailable.",
            election.id,
            exc_info=True,
        )
        return jsonify({"error": "Election signing key is unavailable"}), 503

    return jsonify({**components, "election_id": election.id})


@main.route('/vote/request-token', methods=['POST'])
@login_required
def request_blind_token():
    """Issue one identity-separated blind signature per voter and election."""
    from app.models import Election, VoteReceipt, BlindSignatureToken
    from app.security.blind_signature import (
        BlindSigningKeyError,
        blind_sign,
        ensure_election_blind_signing_key,
    )

    data = request.get_json(silent=True)
    required = {"blinded_ballot", "election_id"}
    if not data or not required.issubset(data):
        return jsonify({"error": "Missing blinded_ballot or election_id"}), 400

    # Eligibility checks (same as /vote)
    try:
        election_id = int(data["election_id"])
    except (TypeError, ValueError):
        current_app.logger.debug("Rejected non-integer election_id")
        return jsonify({"error": "Invalid election_id"}), 400

    active_election = (
        db.session.query(Election)
        .filter(Election.id == election_id)
        # A shared lock prevents the manager's exclusive close transition
        # while this authorization transaction is active. MySQL permits FOR
        # SHARE with SELECT-only credentials, preserving least privilege.
        .with_for_update(read=True)
        .first()
    )
    if not active_election or not active_election.is_open:
        return jsonify({"error": "Election is not open"}), 409

    try:
        locked_user, enrolment = lock_and_validate_voter(db, current_user.id)
    except IneligibleVoterError:
        current_app.logger.info(
            "Rejected blind authorization for an ineligible voter."
        )
        db.session.rollback()
        return jsonify({"error": "Not eligible to vote"}), 403

    candidates = Candidate.query.filter_by(election_id=active_election.id).all()
    region_ids = {candidate.region_id for candidate in candidates}
    positions = {candidate.position for candidate in candidates}
    if len(region_ids) != 1 or len(positions) != 1:
        db.session.rollback()
        return jsonify(
            {"error": "Election is not a single-region, single-contest ballot"}
        ), 409
    if enrolment.region_id not in region_ids:
        db.session.rollback()
        return jsonify({"error": "Election is outside your enrolled region"}), 403

    try:
        blinded_int = int(data['blinded_ballot'], 16)
    except (ValueError, TypeError):
        logging.getLogger(__name__).debug("Handled exception in app/routes/main.py", exc_info=True)
        return jsonify({"error": "Invalid blinded_ballot format"}), 400

    existing_token = (
        BlindSignatureToken.query.filter_by(
            user_id=locked_user.id,
            election_id=active_election.id,
        )
        .with_for_update(read=True)
        .first()
    )
    existing_receipt = VoteReceipt.query.filter_by(
        user_id=locked_user.id,
        election_id=active_election.id,
    ).first()

    if existing_token:
        return jsonify(
            {"error": "A ballot authorization was already issued for this election"}
        ), 409
    if existing_receipt:
        return jsonify({"error": "Already voted in this election"}), 409

    try:
        ensure_election_blind_signing_key(
            current_app.instance_path,
            active_election.id,
            active_election.blind_signing_key_id,
        )
        blind_sig = blind_sign(
            blinded_int,
            current_app.instance_path,
            active_election.id,
        )
    except (ValueError, TypeError):
        current_app.logger.debug("Rejected invalid blinded ballot value", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Invalid blinded ballot value"}), 400
    except BlindSigningKeyError:
        db.session.rollback()
        current_app.logger.error(
            "The blind-signing key for election %s is unavailable.",
            active_election.id,
            exc_info=True,
        )
        return jsonify({"error": "Election signing key is unavailable"}), 503

    # Store only the fact that one signature was issued. Do not store any
    # ballot-derived value or cast state beside the voter's identity.
    db.session.add(
        BlindSignatureToken(
            user_id=locked_user.id,
            election_id=active_election.id,
        )
    )

    try:
        db.session.flush()
    except IntegrityError:
        logging.getLogger(__name__).debug("Handled exception in app/routes/main.py", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Already voted"}), 409

    db.session.commit()
    record_audit_event(
        actor_id=locked_user.id,
        action='ballot_authorization.issue',
        target_type='election',
        target_id=active_election.id,
    )

    return jsonify({
        "blind_signature": hex(blind_sig),
        "election_id": active_election.id,
    })


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
    from app.models import Election, SpentBallotNullifier, Vote
    from app.security.blind_signature import (
        BlindSigningKeyError,
        ensure_election_blind_signing_key,
        verify_unblinded_signature,
    )

    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or 'ballot' not in data
        or 'signature' not in data
    ):
        return jsonify({"error": "Missing ballot or signature"}), 400

    try:
        ballot_hex = data['ballot']
        ballot_bytes = bytes.fromhex(ballot_hex)
        ballot_json = _json.loads(ballot_bytes.decode('utf-8'))
        sig_int = int(data['signature'], 16)
    except (ValueError, TypeError, _json.JSONDecodeError):
        logging.getLogger(__name__).debug("Handled exception in app/routes/main.py", exc_info=True)
        return jsonify({"error": "Invalid ballot or signature format"}), 400

    if not isinstance(ballot_json, dict):
        return jsonify({"error": "Malformed ballot"}), 400

    # Parse and validate the election before choosing a verification key. This
    # ordering ensures an Election A authorization cannot become a ballot in B.
    candidate_id = ballot_json.get('candidate_id')
    election_id = ballot_json.get('election_id')
    nonce = ballot_json.get('nonce')
    if not candidate_id or not election_id or not nonce:
        return jsonify({"error": "Malformed ballot"}), 400
    try:
        candidate_id = int(candidate_id)
        election_id = int(election_id)
    except (TypeError, ValueError):
        current_app.logger.debug("Rejected non-integer ballot identifiers")
        return jsonify({"error": "Malformed ballot"}), 400
    if (
        not isinstance(nonce, str)
        or len(nonce) != 64
        or any(ch not in "0123456789abcdef" for ch in nonce)
    ):
        return jsonify({"error": "Malformed ballot nullifier"}), 400

    election = (
        db.session.query(Election)
        .filter(Election.id == election_id)
        .with_for_update(read=True)
        .first()
    )
    if not election or not election.is_open:
        return jsonify({"error": "Election is not open"}), 409

    try:
        ensure_election_blind_signing_key(
            current_app.instance_path,
            election.id,
            election.blind_signing_key_id,
        )
        signature_valid = verify_unblinded_signature(
            ballot_bytes,
            sig_int,
            current_app.instance_path,
            election.id,
        )
    except BlindSigningKeyError:
        current_app.logger.error(
            "The blind-signing key for election %s is unavailable.",
            election.id,
            exc_info=True,
        )
        return jsonify({"error": "Election signing key is unavailable"}), 503
    if not signature_valid:
        return jsonify({"error": "Invalid signature"}), 403

    # The database composite foreign key and this lookup both prevent a
    # candidate from being submitted under another election.
    candidate = Candidate.query.filter_by(
        id=candidate_id,
        election_id=election.id,
    ).first()
    if not candidate:
        return jsonify({"error": "Candidate is not in this election"}), 400

    election_candidates = Candidate.query.filter_by(election_id=election.id).all()
    if (
        len({item.region_id for item in election_candidates}) != 1
        or len({item.position for item in election_candidates}) != 1
    ):
        db.session.rollback()
        return jsonify(
            {"error": "Election is not a single-region, single-contest ballot"}
        ), 409

    # Replay prevention is identity-free. The signed ballot binds this nonce to
    # the exact candidate and election; the unique nullifier blocks replays.
    nonce_hash = hashlib.sha256(nonce.encode('utf-8')).hexdigest()
    from datetime import datetime, timezone
    spent_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Store anonymous ballot
    ballot_nonce = secrets.token_hex(32)
    ts = datetime.now(timezone.utc)
    vote_hash = hashlib.sha256(
        f"{ballot_nonce}:{election.id}:{candidate_id}:{ts.isoformat()}".encode()
    ).hexdigest()

    vote = Vote(
        voter_token=ballot_nonce,
        election_id=election.id,
        candidate_id=candidate_id,
        position=candidate.position,
        vote_hash=vote_hash,
        created_at=ts.replace(tzinfo=None),
    )
    db.session.add_all(
        [
            vote,
            SpentBallotNullifier(
                election_id=election.id,
                nullifier_hash=nonce_hash,
                spent_at=spent_at,
            ),
        ]
    )

    try:
        db.session.commit()
    except IntegrityError:
        logging.getLogger(__name__).debug("Handled exception in app/routes/main.py", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Ballot was already submitted or is invalid"}), 409

    record_audit_event(
        actor_id=None,
        action='ballot.cast',
        target_type='election',
        target_id=election.id,
    )
    return jsonify({"status": "ok", "message": "Your anonymous ballot has been recorded."})


@main.route("/results")
@roles_required("manager")  # managers only
def results():
    if not current_user.is_manager:
        flash_once('Access denied')
        return redirect(url_for('main.dashboard'))

    from app.models import Election
    from app.services.results_service import ResultsUnavailableError, get_vote_tallies
    from datetime import datetime, timezone

    elections = Election.query.order_by(Election.created_at.desc()).all()
    requested_id = request.args.get("election_id", type=int)
    selected_election = (
        db.session.get(Election, requested_id)
        if requested_id is not None
        else next((e for e in elections if e.status == "closed"), None)
        or next((e for e in elections if e.is_open), None)
    )
    if selected_election is None:
        votes = {}
    else:
        try:
            votes = get_vote_tallies(selected_election.id)
        except ResultsUnavailableError:
            current_app.logger.error(
                "Results page unavailable for election %s",
                selected_election.id,
                exc_info=True,
            )
            abort(503, description="Authoritative election results are unavailable")
    total_votes = sum(item["votes"] for item in votes)

    return render_template(
        'results.html',
        votes=votes,
        total_votes=total_votes,
        timestamp=datetime.now(timezone.utc),
        admin_user=current_user.username,
        elections=elections,
        selected_election=selected_election,
    )

@main.errorhandler(403)
def forbidden(_):
    flash_once("Access denied")
    return redirect(url_for("main.dashboard"))
