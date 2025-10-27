from datetime import datetime
import hashlib
from sqlalchemy.exc import IntegrityError


def cast_anonymous_vote(db, user, candidate):
    """
    Temporary compatibility layer for casting a vote.

    Current implementation records a regular Vote row and marks the user as
    having voted, preserving the one-vote-per-user constraint via DB unique
    index. A cryptographic hash is stored for basic integrity/audit purposes.

    This function is intentionally light to allow future migration to a fully
    anonymized ballot storage without changing route handlers.
    """
    from app.models import Vote

    # Create a reproducible-but-unique hash for this vote event
    payload = f"{user.id}:{candidate.id}:{datetime.utcnow().isoformat()}".encode()
    vote_hash = hashlib.sha256(payload).hexdigest()

    vote = Vote(
        user_id=user.id,
        candidate_id=candidate.id,
        position=candidate.position,
        vote_hash=vote_hash,
        created_at=datetime.utcnow(),
    )
    db.session.add(vote)

    # Mark user as having voted
    user.has_voted = True
    db.session.add(user)

    try:
        db.session.commit()
    except IntegrityError:
        # Surface duplicate vote attempts to caller
        raise