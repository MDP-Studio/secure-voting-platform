import hashlib
import secrets
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError


def cast_anonymous_vote(db, user, candidate):
    """
    Cast an anonymous vote.

    Anonymity design:
    -----------------
    The ballot is stored with a cryptographically random nonce
    (``secrets.token_hex(32)``) that has ZERO mathematical relationship
    to the voter's identity.  Even with full compromise of the database,
    application secrets, and source code, there is no stored mapping from
    a Vote record back to a User.

    Double-vote prevention is enforced by the ``user.has_voted`` flag,
    which is checked by the route handler *before* this function is
    called and then set atomically within the same DB transaction.

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
    from app.models import Vote

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

    # Mark user as having voted (application-level double-vote guard).
    user.has_voted = True
    db.session.add(user)

    try:
        db.session.commit()
    except IntegrityError:
        raise
