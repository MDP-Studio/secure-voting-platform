"""
End-to-end test for the RSA blind signature voting protocol.

Tests the complete cryptographic flow:
  hash → blind → sign → unblind → verify

This validates that the server-side and (simulated) client-side
math produces correct, verifiable signatures without the server
ever seeing the actual ballot contents.
"""
import json
import hashlib
import secrets
import pytest
from app.security.blind_signature import (
    generate_blind_signing_keypair,
    get_public_key_components,
    hash_ballot,
    blind_sign,
    verify_unblinded_signature,
)


class TestBlindSignatureCrypto:
    """Unit tests for the blind signature cryptographic primitives."""

    def test_keypair_generation(self, app):
        """Keys are generated and can be loaded."""
        with app.app_context():
            components = get_public_key_components(app.instance_path)
            assert 'n' in components
            assert 'e' in components
            n = int(components['n'], 16)
            e = int(components['e'], 16)
            assert n > 0
            assert e == 65537

    def test_full_blind_signature_protocol(self, app):
        """
        Simulate the complete blind signature protocol:
        Client blinds → Server signs blind → Client unblinds → Verify.
        """
        with app.app_context():
            instance = app.instance_path
            components = get_public_key_components(instance)
            n = int(components['n'], 16)
            e = int(components['e'], 16)

            # 1. Client creates ballot
            ballot = json.dumps({
                "candidate_id": 1,
                "nonce": secrets.token_hex(32),
                "election_id": 1
            }).encode('utf-8')

            # 2. Client computes FDH(ballot)
            m = hash_ballot(ballot, n)

            # 3. Client generates blinding factor r
            r = secrets.randbelow(n - 3) + 2  # r in [2, n-2]

            # 4. Client blinds: blinded = m * r^e mod n
            r_e = pow(r, e, n)
            blinded = (m * r_e) % n

            # 5. Server signs the blinded message (never sees ballot)
            blind_sig = blind_sign(blinded, instance)

            # 6. Client unblinds: sig = blind_sig * r^(-1) mod n
            r_inv = pow(r, -1, n)
            signature = (blind_sig * r_inv) % n

            # 7. Verify: sig^e mod n == FDH(ballot)
            assert verify_unblinded_signature(ballot, signature, instance)

    def test_wrong_ballot_fails_verification(self, app):
        """Modified ballot should fail signature verification."""
        with app.app_context():
            instance = app.instance_path
            components = get_public_key_components(instance)
            n = int(components['n'], 16)
            e = int(components['e'], 16)

            # Sign one ballot
            ballot = b'{"candidate_id":1,"nonce":"aaa"}'
            m = hash_ballot(ballot, n)
            r = secrets.randbelow(n - 3) + 2
            blinded = (m * pow(r, e, n)) % n
            blind_sig = blind_sign(blinded, instance)
            signature = (blind_sig * pow(r, -1, n)) % n

            # Verify with different ballot → must fail
            fake_ballot = b'{"candidate_id":2,"nonce":"bbb"}'
            assert not verify_unblinded_signature(fake_ballot, signature, instance)

    def test_server_never_sees_ballot(self, app):
        """
        The blinded message should look random — it should NOT equal
        the FDH hash of the actual ballot.
        """
        with app.app_context():
            instance = app.instance_path
            components = get_public_key_components(instance)
            n = int(components['n'], 16)
            e = int(components['e'], 16)

            ballot = b'{"candidate_id":1,"nonce":"test"}'
            m = hash_ballot(ballot, n)

            r = secrets.randbelow(n - 3) + 2
            blinded = (m * pow(r, e, n)) % n

            # The blinded value must NOT equal the original hash
            assert blinded != m, "Blinding failed — server would see the actual ballot hash"


class TestBlindVoteRoutes:
    """Integration tests for the blind vote HTTP endpoints."""

    def test_blind_key_endpoint(self, client):
        """GET /vote/blind-key returns public key components."""
        resp = client.get('/vote/blind-key')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'n' in data
        assert 'e' in data
        n = int(data['n'], 16)
        assert n > 0

    def test_request_token_requires_auth(self, client):
        """POST /vote/request-token without login should fail."""
        resp = client.post('/vote/request-token',
                           json={"blinded_ballot": "abc", "nonce_hash": "def"},
                           content_type='application/json')
        # Should redirect to login (302) or return error
        assert resp.status_code in (302, 401, 403)

    def test_cast_endpoint_rejects_bad_input(self, client):
        """POST /vote/cast with invalid data should return 400 or 403."""
        # Invalid hex ballot
        resp = client.post('/vote/cast',
                           json={"ballot": "deadbeef", "signature": "1234"},
                           content_type='application/json')
        assert resp.status_code in (400, 403)

        # Valid JSON ballot but wrong signature
        fake_ballot = json.dumps({"candidate_id": 1, "nonce": "abc"}).encode().hex()
        resp2 = client.post('/vote/cast',
                            json={"ballot": fake_ballot, "signature": "ff" * 128},
                            content_type='application/json')
        assert resp2.status_code == 403

    def test_full_blind_vote_protocol_via_http(self, client, app):
        """
        End-to-end HTTP test: login → request blind token → cast anonymously.
        Simulates the client-side JS math in Python.
        """
        from app.security.blind_signature import hash_ballot, get_public_key_components

        # Login
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        with app.app_context():
            instance = app.instance_path
            components = get_public_key_components(instance)
            n = int(components['n'], 16)
            e = int(components['e'], 16)

        # Create ballot
        nonce = secrets.token_hex(32)
        ballot = json.dumps({
            "candidate_id": 1,
            "nonce": nonce,
            "election_id": 1
        }).encode('utf-8')
        ballot_hex = ballot.hex()

        # Compute FDH and blind
        m = hash_ballot(ballot, n)
        r = secrets.randbelow(n - 3) + 2
        blinded = (m * pow(r, e, n)) % n
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()

        # Request blind signature (authenticated)
        token_resp = client.post('/vote/request-token',
                                 json={
                                     "blinded_ballot": hex(blinded),
                                     "nonce_hash": nonce_hash,
                                 },
                                 content_type='application/json')
        assert token_resp.status_code == 200, f"Token request failed: {token_resp.get_json()}"
        blind_sig = int(token_resp.get_json()['blind_signature'], 16)

        # Unblind
        signature = (blind_sig * pow(r, -1, n)) % n

        # Cast anonymously (new client, no cookies)
        anon_client = app.test_client()
        cast_resp = anon_client.post('/vote/cast',
                                      json={
                                          "ballot": ballot_hex,
                                          "signature": hex(signature),
                                      },
                                      content_type='application/json')
        assert cast_resp.status_code == 200, f"Cast failed: {cast_resp.get_json()}"
        assert cast_resp.get_json()['status'] == 'ok'

        # Verify vote was recorded anonymously
        with app.app_context():
            from app.models import Vote
            vote = Vote.query.order_by(Vote.id.desc()).first()
            assert vote is not None
            assert vote.candidate_id == 1
            # Vote has NO user_id — truly anonymous
            assert not hasattr(vote, 'user_id') or getattr(vote, 'user_id', None) is None
