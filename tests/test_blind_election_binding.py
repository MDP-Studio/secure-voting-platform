"""Regression tests for immutable, election-bound blind-signing keys."""

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import secrets
import shutil

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security import blind_signature
from app import db
from app.models import Candidate, Election, Region, Vote
from app.services.election_key_service import reconcile_open_election_keys


def _authorize_ballot(instance_path, election_id, ballot):
    components = blind_signature.get_public_key_components(
        instance_path,
        election_id,
    )
    modulus = int(components["n"], 16)
    exponent = int(components["e"], 16)
    message = blind_signature.hash_ballot(ballot, modulus)
    blinding_factor = secrets.randbelow(modulus - 3) + 2
    while math.gcd(blinding_factor, modulus) != 1:
        blinding_factor = secrets.randbelow(modulus - 3) + 2
    blinded = (message * pow(blinding_factor, exponent, modulus)) % modulus
    blind_authorization = blind_signature.blind_sign(
        blinded,
        instance_path,
        election_id,
    )
    return (blind_authorization * pow(blinding_factor, -1, modulus)) % modulus


def _blind_for_http(key_data, ballot):
    modulus = int(key_data["n"], 16)
    exponent = int(key_data["e"], 16)
    message = blind_signature.hash_ballot(ballot, modulus)
    blinding_factor = secrets.randbelow(modulus - 3) + 2
    while math.gcd(blinding_factor, modulus) != 1:
        blinding_factor = secrets.randbelow(modulus - 3) + 2
    blinded = (message * pow(blinding_factor, exponent, modulus)) % modulus
    return blinded, blinding_factor, modulus


def test_authorization_for_election_a_cannot_verify_under_election_b(tmp_path):
    instance_path = str(tmp_path)
    election_a = 101
    election_b = 202
    blind_signature.generate_blind_signing_keypair(instance_path, election_a)
    blind_signature.generate_blind_signing_keypair(instance_path, election_b)

    key_a = blind_signature.get_public_key_components(instance_path, election_a)
    key_b = blind_signature.get_public_key_components(instance_path, election_b)
    assert key_a["n"] != key_b["n"]

    ballot = json.dumps(
        {
            "candidate_id": 7,
            # The exploit asks election A to authorize a ballot that targets B.
            "election_id": election_b,
            "nonce": secrets.token_hex(32),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    authorization = _authorize_ballot(instance_path, election_a, ballot)

    assert blind_signature.verify_unblinded_signature(
        ballot,
        authorization,
        instance_path,
        election_a,
    )
    assert not blind_signature.verify_unblinded_signature(
        ballot,
        authorization,
        instance_path,
        election_b,
    )


def test_http_authorization_for_a_cannot_cast_ballot_in_b(client, app):
    """Reproduce and block the prior cross-election double-vote attack."""
    login = client.post(
        "/login",
        data={"username": "voter1", "password": "Password@123!"},
    )
    assert login.status_code == 302

    with app.app_context():
        election_a = Election.query.filter_by(status="open").one()
        region = Region.query.filter_by(name="Sydney").one()
        election_b = Election(name="Election B", status="draft")
        db.session.add(election_b)
        db.session.flush()
        candidate_b = Candidate(
            name="Candidate B",
            party="Independent",
            position="House of Representatives",
            region_id=region.id,
            election_id=election_b.id,
        )
        db.session.add(candidate_b)
        db.session.commit()
        election_a_id = election_a.id
        election_b_id = election_b.id
        candidate_b_id = candidate_b.id
        key_b = blind_signature.ensure_election_blind_signing_key(
            app.instance_path,
            election_b_id,
            None,
            allow_create=True,
        )
        election_b.blind_signing_key_id = key_b["key_id"]
        db.session.commit()

    ballot_for_b = json.dumps(
        {
            "candidate_id": candidate_b_id,
            "election_id": election_b_id,
            "nonce": secrets.token_hex(32),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key_a = client.get(
        f"/vote/blind-key?election_id={election_a_id}"
    ).get_json()
    blinded_a, factor_a, modulus_a = _blind_for_http(key_a, ballot_for_b)
    authorization_a = client.post(
        "/vote/request-token",
        json={
            "blinded_ballot": hex(blinded_a),
            "election_id": election_a_id,
        },
    )
    assert authorization_a.status_code == 200
    signature_a = (
        int(authorization_a.get_json()["blind_signature"], 16)
        * pow(factor_a, -1, modulus_a)
    ) % modulus_a

    with app.app_context():
        db.session.get(Election, election_a_id).status = "closed"
        db.session.get(Election, election_b_id).status = "open"
        db.session.commit()

    rejected = app.test_client().post(
        "/vote/cast",
        json={"ballot": ballot_for_b.hex(), "signature": hex(signature_a)},
    )
    assert rejected.status_code == 403
    with app.app_context():
        assert Vote.query.filter_by(election_id=election_b_id).count() == 0

    # The same voter may obtain B's legitimate authorization, but can persist
    # exactly one B ballot. This closes the original two-votes-in-B exploit.
    ballot_b = json.dumps(
        {
            "candidate_id": candidate_b_id,
            "election_id": election_b_id,
            "nonce": secrets.token_hex(32),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key_b = client.get(
        f"/vote/blind-key?election_id={election_b_id}"
    ).get_json()
    blinded_b, factor_b, modulus_b = _blind_for_http(key_b, ballot_b)
    authorization_b = client.post(
        "/vote/request-token",
        json={
            "blinded_ballot": hex(blinded_b),
            "election_id": election_b_id,
        },
    )
    assert authorization_b.status_code == 200
    signature_b = (
        int(authorization_b.get_json()["blind_signature"], 16)
        * pow(factor_b, -1, modulus_b)
    ) % modulus_b
    accepted = app.test_client().post(
        "/vote/cast",
        json={"ballot": ballot_b.hex(), "signature": hex(signature_b)},
    )
    assert accepted.status_code == 200
    with app.app_context():
        assert Vote.query.filter_by(election_id=election_b_id).count() == 1


def test_concurrent_first_use_publishes_one_complete_keypair(tmp_path):
    instance_path = str(tmp_path)
    election_id = 303

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                blind_signature.generate_blind_signing_keypair,
                instance_path,
                election_id,
            )
            for _ in range(16)
        ]
        for future in futures:
            future.result()

    components = [
        blind_signature.get_public_key_components(instance_path, election_id)
        for _ in range(8)
    ]
    assert all(component == components[0] for component in components)

    key_dir = tmp_path / blind_signature.KEY_ROOT / f"election-{election_id}"
    assert (key_dir / blind_signature.PRIVATE_KEY_FILE).is_file()
    assert (key_dir / blind_signature.PUBLIC_KEY_FILE).is_file()
    assert (key_dir / blind_signature.KEY_METADATA_FILE).is_file()
    assert not list((tmp_path / blind_signature.KEY_ROOT).glob(".election-*.tmp-*"))


def test_lost_anchored_key_fails_closed_without_regeneration(client, app):
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election_id = election.id
        expected_key_id = election.blind_signing_key_id
        key_dir = (
            Path(app.instance_path)
            / blind_signature.KEY_ROOT
            / f"election-{election_id}"
        )
        assert expected_key_id
        assert key_dir.is_dir()
        shutil.rmtree(key_dir)
        with blind_signature._cache_lock:
            blind_signature._key_cache.clear()

    response = client.get(f"/vote/blind-key?election_id={election_id}")
    assert response.status_code == 503
    assert response.get_json()["error"] == "Election signing key is unavailable"
    assert not key_dir.exists()


def test_incomplete_existing_keypair_fails_closed_without_replacement(tmp_path):
    election_id = 404
    key_dir = tmp_path / blind_signature.KEY_ROOT / f"election-{election_id}"
    key_dir.mkdir(parents=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    private_path = key_dir / blind_signature.PRIVATE_KEY_FILE
    private_path.write_bytes(private_bytes)

    with pytest.raises(blind_signature.BlindSigningKeyError):
        blind_signature.generate_blind_signing_keypair(
            str(tmp_path),
            election_id,
        )

    assert private_path.read_bytes() == private_bytes
    assert not (key_dir / blind_signature.PUBLIC_KEY_FILE).exists()


def test_post_migration_reconciler_anchors_only_unused_open_election(app, tmp_path):
    with app.app_context():
        Election.query.filter_by(status="open").update({"status": "closed"})
        election = Election(name="Eligible legacy election", status="open")
        db.session.add(election)
        db.session.commit()

        assert reconcile_open_election_keys(str(tmp_path)) == 1
        db.session.commit()
        assert election.blind_signing_key_id
        assert reconcile_open_election_keys(str(tmp_path)) == 0


def test_post_migration_reconciler_refuses_ambiguous_authority(app, tmp_path):
    with app.app_context():
        Election.query.filter_by(status="open").update({"status": "closed"})
        election = Election(
            name="Ambiguous legacy election",
            status="open",
            blind_key_recovery_required=True,
        )
        db.session.add(election)
        db.session.commit()

        with pytest.raises(
            blind_signature.BlindSigningKeyError,
            match="Manual recovery is required",
        ):
            reconcile_open_election_keys(str(tmp_path))

        assert election.blind_signing_key_id is None
