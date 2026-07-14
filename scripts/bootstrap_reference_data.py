"""Create non-secret reference rows required by an empty SecureVote schema.

This bootstrap intentionally creates no users, passwords, electoral-roll
records, elections, candidates, or ballots. Privileged identities must be
provisioned through a separate controlled process.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.models import Region, Role


ROLES = (
    ("voter", "Can cast one vote"),
    ("delegate", "Manages candidates, cannot vote"),
    ("manager", "System admin, cannot vote"),
)

REGIONS = (
    "Sydney",
    "VIC east",
    "VIC west",
    "NSW",
    "SA",
    "QLD",
    "WA",
    "TAS",
    "ACT",
    "NT",
)


def bootstrap_reference_data() -> None:
    app = create_app()
    with app.app_context():
        for name, description in ROLES:
            role = Role.query.filter_by(name=name).first()
            if role is None:
                db.session.add(Role(name=name, description=description))
            elif not role.description:
                role.description = description

        for name in REGIONS:
            if Region.query.filter_by(name=name).first() is None:
                db.session.add(Region(name=name))

        db.session.commit()


if __name__ == "__main__":
    bootstrap_reference_data()
