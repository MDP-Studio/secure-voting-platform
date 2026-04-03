"""
Election management routes — create, open, close elections.
Manager-only access.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime, timezone
from app import db
from app.models import Election
from app.utils.auth_decorators import roles_required

elections_bp = Blueprint('elections', __name__, url_prefix='/elections')


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
            election.open_at = datetime.fromisoformat(open_at)
        except ValueError:
            pass
    if close_at:
        try:
            election.close_at = datetime.fromisoformat(close_at)
        except ValueError:
            pass

    db.session.add(election)
    db.session.commit()
    flash(f'Election "{name}" created.', 'success')
    return redirect(url_for('elections.list_elections'))


@elections_bp.route('/<int:election_id>/open', methods=['POST'])
@roles_required('manager')
def open_election(election_id):
    """Open an election for voting."""
    election = Election.query.get_or_404(election_id)
    if election.status == 'closed':
        flash('Cannot reopen a closed election.', 'error')
        return redirect(url_for('elections.list_elections'))

    election.status = 'open'
    if not election.open_at:
        election.open_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash(f'Election "{election.name}" is now open for voting.', 'success')
    return redirect(url_for('elections.list_elections'))


@elections_bp.route('/<int:election_id>/close', methods=['POST'])
@roles_required('manager')
def close_election(election_id):
    """Close an election — no more votes accepted."""
    election = Election.query.get_or_404(election_id)
    election.status = 'closed'
    election.close_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash(f'Election "{election.name}" has been closed.', 'success')
    return redirect(url_for('elections.list_elections'))
