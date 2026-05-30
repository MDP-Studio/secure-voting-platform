"""
Audit log viewer for managers.
Reads HMAC-backed JSON-lines audit log and displays in a paginated table.
"""
import logging

import json
import os
from flask import Blueprint, render_template, current_app, flash
from flask_login import login_required
from app.utils.auth_decorators import roles_required

audit_bp = Blueprint('audit', __name__, url_prefix='/admin/audit')


def _read_audit_entries(path, max_entries=500):
    """Read the last N audit log entries (newest first)."""
    entries = []
    if not os.path.exists(path):
        return entries
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logging.getLogger(__name__).debug("Handled exception in app/routes/audit.py", exc_info=True)
                    continue
    except Exception:
        logging.getLogger(__name__).debug("Handled exception in app/routes/audit.py", exc_info=True)
        pass
    # Return newest first, capped
    return list(reversed(entries[-max_entries:]))


@audit_bp.route('/')
@roles_required('manager')
def view_audit_log():
    """Display the audit log with chain integrity status."""
    audit_path = current_app.config.get('AUDIT_LOG_PATH') or os.path.join(
        current_app.instance_path, 'audit.log'
    )

    entries = _read_audit_entries(audit_path)

    # Verify chain integrity
    chain_ok = False
    chain_errors = []
    key = current_app.config.get('AUDIT_HMAC_KEY') or os.environ.get('AUDIT_HMAC_KEY')
    if key:
        from app.logging_service import verify_audit
        chain_ok, chain_errors = verify_audit(audit_path, key.encode('utf-8'))
    else:
        chain_errors = ['AUDIT_HMAC_KEY not configured — chain verification unavailable']

    return render_template(
        'audit_log.html',
        entries=entries,
        chain_ok=chain_ok,
        chain_errors=chain_errors,
        total_entries=len(entries),
    )
