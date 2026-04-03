import hashlib
import secrets
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError


class AlreadyVotedError(Exception):
    """Raised when a user attempts to vote more than once."""
    pass


def cast_anonymous_vote(db, user, candidate):
    """
    Cast an anonymous vote with pessimistic locking.

    Anonymity design:
    -----------------
    The ballot is stored with a cryptographically random nonce
    (``secrets.token_hex(32)``) that has ZERO mathematical relationship
    to the voter's identity.  Even with full compromise of the database,
    application secrets, and source code, there is no stored mapping from
    a Vote record back to a User.

    Concurrency safety:
    -------------------
    A ``SELECT ... FOR UPDATE`` row lock is acquired on the User record
    before checking ``has_voted``.  This prevents the TOCTOU race where
    two concurrent requests both read ``has_voted=False`` before either
    commits.  The lock serializes concurrent vote attempts for the same
    user at the database level — the second request will block until the
    first commits, then see ``has_voted=True`` and abort.

    On SQLite (development/testing) FOR UPDATE is a no-op, but SQLite's
    write-lock-per-transaction provides equivalent serialization.

    Threat model / limitations:
    ---------------------------
    This is a server-side voting system.  The Flask process transiently
    holds both the voter identity and the ballot content in memory during
    the HTTP request.  True end-to-end verifiable ballot secrecy (blind
    signatures, mix-nets, homomorphic tallying) requires a multi-party
    cryptographic protocol beyond the scope of a monolithic web app.
    What this design *does* guarantee is that the **persisted data** is
    unlinkable — no post-hoc de-anonymization is possible.
    """
    from app.models import User, Vote

    # --- Pessimistic lock: SELECT ... FOR UPDATE on the user row ---
    # This serializes concurrent vote attempts for the same user_id.
    # On MySQL/PostgreSQL this acquires a row-level exclusive lock.
    # On SQLite the with_for_update() is a no-op but SQLite's
    # single-writer model provides equivalent protection.
    locked_user = (
        db.session.query(User)
        .filter(User.id == user.id)
        .with_for_update()
        .first()
    )

    if locked_user is None or locked_user.has_voted:
        raise AlreadyVotedError("User has already voted")

    # --- Create the anonymous ballot ---
    # Random 256-bit nonce — no relationship to user identity.
    ballot_nonce = secrets.token_hex(32)

    # Integrity hash covers the nonce + candidate + timestamp for audit.
    ts = datetime.now(timezone.utc).isoformat()
    payload = f"{ballot_nonce}:{candidate.id}:{ts}".encode()
    vote_hash = hashlib.sha256(payload).hexdigest()

    vote = Vote(
        voter_token=ballot_nonce,
        candidate_id=candidate.id,
        position=candidate.position,
        vote_hash=vote_hash,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(vote)

    # Mark user as having voted under the same lock.
    locked_user.has_voted = True

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise AlreadyVotedError("Concurrent vote detected")
