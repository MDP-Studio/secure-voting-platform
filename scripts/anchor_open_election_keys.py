"""Run the controlled post-migration election-key reconciliation."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.services.election_key_service import reconcile_open_election_keys


def main() -> None:
    app = create_app()
    with app.app_context():
        try:
            count = reconcile_open_election_keys(app.instance_path)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    print(f"Validated open-election keys; created {count} legacy anchor(s).")


if __name__ == "__main__":
    main()
