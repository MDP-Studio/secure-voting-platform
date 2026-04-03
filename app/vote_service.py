import hashlib
import secrets
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError


class AlreadyVotedError(Exception):
    """Raised when a user attempts to vote more than once."""
    pass


def cast_anonymous_vote(db, user, candidate):
    """
    Cast an anonymous vote with database-level double-vote prevention.

    Anonymity design:
    -----------------
    The ballot (``Vote``) stores a cryptographically random nonce with
    ZERO relationship to the voter.  No FK, no HMAC, no derivation.

    Concurrency safety:
    -------------------
    Double-vote prevention uses a two-table design:

    1. ``VoteReceipt`` — contains ``UNIQUE(user_id)``.  Records that a
       user voted, but NOT which candidate.  The DB unique constraint is
       the authoritative guard — it cannot be bypassed by application-
       layer race conditions.

    2. ``Vote`` — the anonymous ballot.  Contains the candidate choice
       but NO user identity.

    Both are inserted in the SAME transaction.  If a concurrent thread
    manages to insert a duplicate receipt, the DB rejects the entire
    transaction via IntegrityError, rolling back the anonymous ballot
    as well.  This eliminates the TOCTOU race completely.

    Additionally, ``SELECT ... FOR UPDATE`` is used on the User row as
    a first line of defense (effective on MySQL/PostgreSQL; no-op on
    SQLite).  The DB constraint is the safety net that catches anything
    the lock misses.

    Threat model / limitations:
    ---------------------------
    The VoteReceipt table records that user X voted, but NOT which
    candidate they chose.  An attacker with DB access can see WHO voted
    but not HOW they voted.  This is equivalent to a physical electoral
    roll check-off — standard in real elections.

    The server process transiently knows both identity and ballot during
    the HTTP request.  True end-to-end verifiable ballot secrecy requires
    multi-party cryptographic protocols beyond a monolithic web app.
    """
    from app.models import User, Vote, VoteReceipt

    # --- Pessimistic lock (first line of defense) ---
    # Effective on MySQL/PostgreSQL.  No-op on SQLite but the unique
    # constraint below catches the race regardless.
    locked_user = (
        db.session.query(User)
        .filter(User.id == user.id)
        .with_for_update()
        .first()
    )

    if locked_user is None or locked_user.has_voted:
        raise AlreadyVotedError("User has already voted")

    # --- Create the anonymous ballot ---
    ballot_nonce = secrets.token_hex(32)
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

    # --- Insert vote receipt (DB-level unique constraint) ---
    # This is the authoritative double-vote guard.  If two threads race
    # past the application check, the UNIQUE(user_id) constraint kills
    # the second transaction.
    receipt = VoteReceipt(user_id=user.id)
    db.session.add(receipt)

    # Mark user as having voted (application-level fast guard).
    locked_user.has_voted = True

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Re-read user state after rollback to update has_voted
        refreshed = db.session.get(User, user.id)
        if refreshed and not refreshed.has_voted:
            refreshed.has_voted = True
            db.session.commit()
        raise AlreadyVotedError("Concurrent vote detected — blocked by database constraint")
