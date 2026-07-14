"""Election-scoped anonymous vote transaction service."""

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError


class AlreadyVotedError(Exception):
    """Raised when a voter attempts to vote twice in one election."""


class InvalidElectionError(Exception):
    """Raised when a ballot crosses election boundaries or a poll is closed."""


class IneligibleVoterError(Exception):
    """Raised when locked voter or enrolment state is no longer eligible."""


def lock_and_validate_voter(db, user_id):
    """Lock and re-read authoritative voter eligibility inside a transaction."""
    from app.models import ElectoralRoll, User

    locked_user = (
        db.session.query(User)
        .filter(User.id == user_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked_user is None:
        raise IneligibleVoterError("Voter record is unavailable")

    enrolment = (
        db.session.query(ElectoralRoll)
        .filter(ElectoralRoll.user_id == locked_user.id)
        .populate_existing()
        # Eligibility is read-only for the voter credential. A shared lock
        # blocks concurrent approval-state changes without granting UPDATE on
        # electoral_roll.
        .with_for_update(read=True)
        .first()
    )
    if (
        not locked_user.is_approved
        or not locked_user.email_verified
        or not locked_user.has_role("voter")
        or enrolment is None
        or enrolment.status != "active"
        or not enrolment.verified
    ):
        raise IneligibleVoterError("Voter is not currently eligible")
    return locked_user, enrolment


def cast_anonymous_vote(db, user, candidate, election=None):
    """Record one anonymous ballot and one identity-only election receipt.

    Vote contains the candidate choice but no voter identity. VoteReceipt
    contains the voter and election but no candidate choice. Both rows are
    committed together, and a composite unique constraint on user_id plus
    election_id is the authoritative concurrency guard.
    """
    from app.models import BlindSignatureToken, Election, Vote, VoteReceipt

    election = election or getattr(candidate, "election", None)
    if election is None or candidate.election_id != election.id:
        raise InvalidElectionError("Candidate does not belong to this election")
    locked_election = (
        db.session.query(Election)
        .filter(Election.id == election.id)
        .with_for_update(read=True)
        .first()
    )
    if locked_election is None or not locked_election.is_open:
        raise InvalidElectionError("Election is not open")

    locked_user, enrolment = lock_and_validate_voter(db, user.id)
    if candidate.region_id != enrolment.region_id:
        raise IneligibleVoterError(
            "Candidate is outside the voter's enrolled region"
        )

    existing_receipt = VoteReceipt.query.filter_by(
        user_id=locked_user.id,
        election_id=locked_election.id,
    ).first()
    if existing_receipt:
        raise AlreadyVotedError("User has already voted in this election")
    existing_authorization = BlindSignatureToken.query.filter_by(
        user_id=locked_user.id,
        election_id=locked_election.id,
    ).first()
    if existing_authorization:
        raise AlreadyVotedError(
            "A blind-ballot authorization was already issued for this election"
        )

    ballot_nonce = secrets.token_hex(32)
    timestamp = datetime.now(timezone.utc)
    payload = (
        f"{ballot_nonce}:{locked_election.id}:{candidate.id}:{timestamp.isoformat()}"
    ).encode()
    vote = Vote(
        voter_token=ballot_nonce,
        election_id=locked_election.id,
        candidate_id=candidate.id,
        position=candidate.position,
        vote_hash=hashlib.sha256(payload).hexdigest(),
        created_at=timestamp.replace(tzinfo=None),
    )
    receipt = VoteReceipt(user_id=locked_user.id, election_id=locked_election.id)
    db.session.add_all([vote, receipt])

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise AlreadyVotedError(
            "Concurrent vote detected and blocked by the election receipt constraint"
        ) from exc
