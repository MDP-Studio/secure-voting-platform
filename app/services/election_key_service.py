"""Controlled reconciliation for open-election blind-signing authorities."""

from app import db
from app.models import BlindSignatureToken, Election
from app.security.blind_signature import (
    BlindSigningKeyError,
    ensure_election_blind_signing_key,
)


def reconcile_open_election_keys(instance_path: str) -> int:
    """Validate anchored keys and provision only unambiguous legacy anchors.

    An unanchored open election is eligible for one-time provisioning only when
    no blind authorization has ever been issued for it. Existing anchors are
    validation-only and are never regenerated or rotated here.
    """
    anchored = 0
    elections = (
        db.session.query(Election)
        .filter(Election.status == "open")
        .with_for_update()
        .all()
    )
    for election in elections:
        if election.blind_key_recovery_required:
            raise BlindSigningKeyError(
                "This open election has ambiguous legacy blind-authorization "
                "history. Manual recovery is required."
            )
        has_authorization = (
            BlindSignatureToken.query.filter_by(election_id=election.id).first()
            is not None
        )
        if election.blind_signing_key_id is None and has_authorization:
            raise BlindSigningKeyError(
                "An open election with issued authorizations has no anchored "
                "blind-signing key. Manual recovery is required."
            )

        components = ensure_election_blind_signing_key(
            instance_path,
            election.id,
            election.blind_signing_key_id,
            allow_create=election.blind_signing_key_id is None,
        )
        if election.blind_signing_key_id is None:
            election.blind_signing_key_id = components["key_id"]
            anchored += 1

    return anchored
