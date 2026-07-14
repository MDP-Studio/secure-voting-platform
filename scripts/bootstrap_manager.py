"""Create the first manager from one-shot initialization credentials.

The script is idempotent once any manager exists. It never creates predictable
defaults and never runs in the long-lived web container.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.models import Role, User


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.upper().startswith(("CHANGE_ME", "REPLACE_")):
        raise RuntimeError(f"{name} must be set to a non-placeholder value")
    return value


def bootstrap_manager() -> None:
    app = create_app()
    with app.app_context():
        manager_role = Role.query.filter_by(name="manager").first()
        if manager_role is None:
            raise RuntimeError("Manager role is missing; run reference bootstrap first")

        if User.query.filter_by(role_id=manager_role.id).first() is not None:
            print("A manager already exists; one-time bootstrap skipped.")
            return

        username = _required("BOOTSTRAP_MANAGER_USERNAME")
        email = _required("BOOTSTRAP_MANAGER_EMAIL")
        password = _required("BOOTSTRAP_MANAGER_PASSWORD")
        licence = _required("BOOTSTRAP_MANAGER_LICENSE")
        licence_state = _required("BOOTSTRAP_MANAGER_LICENSE_STATE")

        if User.query.filter_by(username=username).first() is not None:
            raise RuntimeError("Bootstrap manager username is already in use")
        if User.query.filter_by(email=email).first() is not None:
            raise RuntimeError("Bootstrap manager email is already in use")

        manager = User(
            username=username,
            email=email,
            driver_lic_no=licence,
            driver_lic_state=licence_state,
            role=manager_role,
            account_status="approved",
            email_verified=True,
        )
        manager.set_password(password)
        # Force a password change at the first successful login so the
        # bootstrap secret does not remain the manager's standing credential.
        manager.password_changed_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=91)
        )
        db.session.add(manager)
        db.session.commit()
        print("Initial manager created; first login must change its password.")


if __name__ == "__main__":
    bootstrap_manager()
