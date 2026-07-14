"""Election-scoping and result-integrity regression tests."""

import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import db
from app.models import (
    BlindSignatureToken,
    Candidate,
    Election,
    Region,
    ResultSigningPublicKey,
    SignedElectionResult,
    User,
    Vote,
    VoteReceipt,
)
from app.services.results_service import ResultsUnavailableError, get_vote_tallies
from app.security.signing_service import SigningResult
from app.vote_service import (
    AlreadyVotedError,
    IneligibleVoterError,
    InvalidElectionError,
    cast_anonymous_vote,
)


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _login(client, username="voter1", password="Password@123!"):
    return client.post("/login", data={"username": username, "password": password})


def test_vote_receipts_are_scoped_per_election(app):
    """A voter gets one receipt per election, not one receipt for life."""
    with app.app_context():
        first = Election.query.filter_by(status="open").one()
        first_candidate = Candidate.query.filter_by(election_id=first.id).first()
        voter = User.query.filter_by(username="voter1").one()

        cast_anonymous_vote(db, voter, first_candidate, first)
        first.status = "closed"

        second = Election(name="Second Election", status="open", open_at=_utcnow_naive())
        db.session.add(second)
        db.session.flush()
        second_candidate = Candidate(
            name="Second Candidate",
            party="Independent",
            position="Representative",
            region_id=first_candidate.region_id,
            election_id=second.id,
        )
        db.session.add(second_candidate)
        db.session.commit()

        cast_anonymous_vote(db, voter, second_candidate, second)

        assert VoteReceipt.query.filter_by(user_id=voter.id).count() == 2
        assert Vote.query.filter_by(election_id=first.id).count() == 1
        assert Vote.query.filter_by(election_id=second.id).count() == 1


def test_cross_election_candidate_is_rejected(app):
    with app.app_context():
        first = Election.query.filter_by(status="open").one()
        candidate = Candidate.query.filter_by(election_id=first.id).first()
        first.status = "closed"
        second = Election(name="Other Election", status="open", open_at=_utcnow_naive())
        db.session.add(second)
        db.session.commit()

        voter = User.query.filter_by(username="voter1").one()
        with pytest.raises(InvalidElectionError):
            cast_anonymous_vote(db, voter, candidate, second)


def test_locked_eligibility_is_revalidated_before_direct_vote(app):
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        candidate = Candidate.query.filter_by(election_id=election.id).first()
        voter = User.query.filter_by(username="voter1").one()
        voter.account_status = "rejected"
        db.session.commit()

        with pytest.raises(IneligibleVoterError):
            cast_anonymous_vote(db, voter, candidate, election)
        assert Vote.query.count() == 0


def test_direct_vote_rejects_candidate_outside_enrolled_region(app):
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        voter = User.query.filter_by(username="voter1").one()
        other_region = Region(name="Other direct-vote region")
        db.session.add(other_region)
        db.session.flush()
        candidate = Candidate(
            name="Out of region",
            party="Independent",
            position="House of Representatives",
            region_id=other_region.id,
            election_id=election.id,
        )
        db.session.add(candidate)
        db.session.commit()

        with pytest.raises(IneligibleVoterError, match="region"):
            cast_anonymous_vote(db, voter, candidate, election)
        assert Vote.query.count() == 0


def test_open_transition_rejects_multi_contest_roster(client, app):
    _login(client, "admin", "Admin@123456!")
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election.status = "draft"
        first = Candidate.query.filter_by(election_id=election.id).first()
        db.session.add(
            Candidate(
                name="Second contest candidate",
                party="Independent",
                position="A different contest",
                region_id=first.region_id,
                election_id=election.id,
            )
        )
        db.session.commit()
        election_id = election.id

    response = client.post(f"/elections/{election_id}/open")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Election, election_id).status == "draft"


def test_election_schedule_form_uses_explicit_utc(client, app):
    _login(client, "admin", "Admin@123456!")
    page = client.get('/elections/')
    assert page.status_code == 200
    assert b'Opens At (UTC, optional)' in page.data
    assert b'Enter election schedule times in UTC' in page.data

    response = client.post(
        '/elections/create',
        data={
            'name': 'UTC schedule regression',
            'open_at': '2026-08-01T02:30',
            'close_at': '2026-08-01T04:45',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        election = Election.query.filter_by(name='UTC schedule regression').one()
        assert election.open_at == datetime(2026, 8, 1, 2, 30)
        assert election.close_at == datetime(2026, 8, 1, 4, 45)


def test_tallies_preserve_candidates_with_the_same_name(app):
    with app.app_context():
        first_region = Region.query.first()
        second_region = Region(name="Tally Test Region")
        election = Election(name="Draft tally test", status="draft")
        db.session.add_all([second_region, election])
        db.session.flush()
        first = Candidate(
            name="Shared Name",
            party="Independent",
            position="Representative",
            region_id=first_region.id,
            election_id=election.id,
        )
        second = Candidate(
            name="Shared Name",
            party="Independent",
            position="Representative",
            region_id=second_region.id,
            election_id=election.id,
        )
        db.session.add_all([first, second])
        db.session.commit()

        rows = get_vote_tallies(election.id)

        matching = [row for row in rows if row["name"] == "Shared Name"]
        assert len(matching) == 2
        assert {row["candidate_id"] for row in matching} == {first.id, second.id}
        assert {row["region_id"] for row in matching} == {
            first.region_id,
            second.region_id,
        }


def test_candidate_id_remains_identity_when_names_match_in_one_contest(app):
    with app.app_context():
        region = Region.query.first()
        election = Election(name="Same-name candidate test", status="draft")
        db.session.add(election)
        db.session.flush()
        candidates = [
            Candidate(
                name="Alex Smith",
                party=party,
                position="Representative",
                region_id=region.id,
                election_id=election.id,
            )
            for party in ("Party One", "Party Two")
        ]
        db.session.add_all(candidates)
        db.session.commit()

        assert candidates[0].id != candidates[1].id
        assert Candidate.query.filter_by(
            election_id=election.id,
            name="Alex Smith",
        ).count() == 2


def test_blind_authorization_is_election_bound_without_ballot_link(client, app):
    _login(client)
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election_id = election.id

    response = client.post(
        "/vote/request-token",
        json={
            "blinded_ballot": "0x2",
            "election_id": election_id,
        },
    )
    assert response.status_code == 200

    with app.app_context():
        token = BlindSignatureToken.query.one()
        assert token.election_id == election_id
        assert token.user_id is not None
        assert not hasattr(token, "issued_at")
        assert not hasattr(token, "ballot_nonce_hash")
        assert not hasattr(token, "redeemed_at")
        assert VoteReceipt.query.count() == 0


def test_blind_authorization_blocks_a_second_direct_ballot(client, app):
    _login(client)
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        candidate = Candidate.query.filter_by(election_id=election.id).first()
        voter = User.query.filter_by(username="voter1").one()
        db.session.add(
            BlindSignatureToken(
                user_id=voter.id,
                election_id=election.id,
            )
        )
        db.session.commit()

        with pytest.raises(AlreadyVotedError, match="authorization"):
            cast_anonymous_vote(db, voter, candidate, election)


def test_results_signing_fails_closed_when_tally_is_unavailable(client, app, monkeypatch):
    _login(client, "admin", "Admin@123456!")
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election.status = "closed"
        election.close_at = _utcnow_naive()
        db.session.commit()
        election_id = election.id

    def unavailable(_election_id):
        raise ResultsUnavailableError("database unavailable")

    monkeypatch.setattr("app.routes.results.get_vote_tallies", unavailable)
    response = client.post("/results/sign", json={"election_id": election_id})

    assert response.status_code == 503
    with app.app_context():
        assert SignedElectionResult.query.count() == 0


def test_signed_results_are_persisted_for_a_closed_election(client, app, monkeypatch):
    _login(client, "admin", "Admin@123456!")
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election.status = "closed"
        election.close_at = _utcnow_naive()
        db.session.commit()
        election_id = election.id

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    key_id = hashlib.sha256(
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()
    monkeypatch.setattr(
        "app.routes.results.signing_service.sign_data",
        lambda _data: SigningResult(
            signature=b"signed".hex(),
            signer_backend="local-rsa",
            signature_algorithm="rsa-pss-sha256",
            signing_key_id=key_id,
            signing_key_version=None,
            public_key_pem=public_key_pem,
        ),
    )
    response = client.post("/results/sign", json={"election_id": election_id})
    assert response.status_code == 200

    with app.app_context():
        stored = SignedElectionResult.query.filter_by(election_id=election_id).one()
        assert stored.signature == b"signed".hex()
        assert stored.signer_backend == "local-rsa"
        assert stored.signature_algorithm == "rsa-pss-sha256"
        assert stored.signing_key_id == key_id
        assert stored.signing_key_version is None
        archived_key = db.session.get(ResultSigningPublicKey, key_id)
        assert archived_key.public_key_pem == public_key_pem
        assert json.loads(stored.payload)["election_id"] == election_id

    latest = client.get(f"/results/latest?election_id={election_id}")
    assert latest.status_code == 200
    assert latest.get_json()["data"]["election_id"] == election_id
