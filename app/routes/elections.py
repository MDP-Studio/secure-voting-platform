"""
Election management routes — create, open, close elections.
Manager-only access.
"""
import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required, current_user
from datetime import datetime, timezone
from app import db
from app.logging_service import record_audit_event
from app.models import Election
from app.utils.auth_decorators import roles_required

elections_bp = Blueprint('elections', __name__, url_prefix='/elections')


def _parse_utc_datetime(value):
    """Parse a manager-entered timestamp and store UTC without tzinfo."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@elections_bp.route('/')
@roles_required('manager')
def list_elections():
    """List all elections."""
    elections = Election.query.order_by(Election.created_at.desc()).all()
    return render_template('elections/manage.html', elections=elections)


@elections_bp.route('/create', methods=['POST'])
@roles_required('manager')
def create_election():
    """Create a new election in draft status."""
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Election name is required.', 'error')
        return redirect(url_for('elections.list_elections'))

    election = Election(
        name=name,
        status='draft',
        created_by=current_user.id,
    )

    # Parse optional dates
    open_at = request.form.get('open_at')
    close_at = request.form.get('close_at')
    if open_at:
        try:
            election.open_at = _parse_utc_datetime(open_at)
        except ValueError:
            logging.getLogger(__name__).debug("Handled exception in app/routes/elections.py", exc_info=True)
            flash('Open time must be a valid date and time.', 'error')
            return redirect(url_for('elections.list_elections'))
    if close_at:
        try:
            election.close_at = _parse_utc_datetime(close_at)
        except ValueError:
            logging.getLogger(__name__).debug("Handled exception in app/routes/elections.py", exc_info=True)
            flash('Close time must be a valid date and time.', 'error')
            return redirect(url_for('elections.list_elections'))
    if election.open_at and election.close_at and election.close_at <= election.open_at:
        flash('Close time must be after open time.', 'error')
        return redirect(url_for('elections.list_elections'))

    db.session.add(election)
    db.session.commit()
    record_audit_event(
        actor_id=current_user.id,
        action='election.create',
        target_type='election',
        target_id=election.id,
    )
    flash(f'Election "{name}" created.', 'success')
    return redirect(url_for('elections.list_elections'))


@elections_bp.route('/<int:election_id>/open', methods=['POST'])
@roles_required('manager')
def open_election(election_id):
    """Open an election for voting."""
    # Lock the election set so concurrent manager requests cannot open two
    # elections or race a roster mutation across the state transition.
    locked_elections = (
        db.session.query(Election)
        .order_by(Election.id.asc())
        .with_for_update()
        .all()
    )
    election = next((item for item in locked_elections if item.id == election_id), None)
    if election is None:
        abort(404)
    if election.status != 'draft':
        flash('Only a draft election can be opened.', 'error')
        return redirect(url_for('elections.list_elections'))
    if election.blind_key_recovery_required:
        flash(
            'This legacy election requires signing-authority recovery and cannot open.',
            'error',
        )
        return redirect(url_for('elections.list_elections'))
    if any(item.status == 'open' and item.id != election.id for item in locked_elections):
        flash('Close the current election before opening another.', 'error')
        return redirect(url_for('elections.list_elections'))
    if election.candidates.count() == 0:
        flash('Add at least one candidate before opening this election.', 'error')
        return redirect(url_for('elections.list_elections'))
    candidates = election.candidates.all()
    regions = {candidate.region_id for candidate in candidates}
    positions = {candidate.position for candidate in candidates}
    if len(regions) != 1 or len(positions) != 1:
        flash(
            'This prototype supports exactly one region and one contest per election. '
            'Align every candidate before opening it.',
            'error',
        )
        return redirect(url_for('elections.list_elections'))

    # Publish the election's immutable blind-signing key before voting opens.
    # A missing or damaged existing keypair is an integrity failure, so the
    # election remains in draft rather than silently rotating its authority.
    from app.security.blind_signature import (
        BlindSigningKeyError,
        ensure_election_blind_signing_key,
    )

    try:
        key_components = ensure_election_blind_signing_key(
            current_app.instance_path,
            election.id,
            election.blind_signing_key_id,
            allow_create=election.blind_signing_key_id is None,
        )
        election.blind_signing_key_id = key_components["key_id"]
    except BlindSigningKeyError:
        db.session.rollback()
        current_app.logger.error(
            "Could not prepare the blind-signing key for election %s.",
            election.id,
            exc_info=True,
        )
        flash(
            'The election signing key is unavailable. The election was not opened.',
            'error',
        )
        return redirect(url_for('elections.list_elections'))

    election.status = 'open'
    if not election.open_at:
        election.open_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if election.close_at and election.close_at <= election.open_at:
        flash('Close time must be after open time.', 'error')
        return redirect(url_for('elections.list_elections'))
    db.session.commit()
    record_audit_event(
        actor_id=current_user.id,
        action='election.open',
        target_type='election',
        target_id=election.id,
    )
    flash(f'Election "{election.name}" is now open for voting.', 'success')
    return redirect(url_for('elections.list_elections'))


@elections_bp.route('/<int:election_id>/close', methods=['POST'])
@roles_required('manager')
def close_election(election_id):
    """Close an election — no more votes accepted."""
    election = (
        db.session.query(Election)
        .filter(Election.id == election_id)
        .with_for_update()
        .first()
    )
    if election is None:
        abort(404)
    if election.status != 'open':
        flash('Only an open election can be closed.', 'error')
        return redirect(url_for('elections.list_elections'))
    election.status = 'closed'
    election.close_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    record_audit_event(
        actor_id=current_user.id,
        action='election.close',
        target_type='election',
        target_id=election.id,
    )
    flash(f'Election "{election.name}" has been closed.', 'success')
    return redirect(url_for('elections.list_elections'))
