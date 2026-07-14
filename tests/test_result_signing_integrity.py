"""Regression tests for durable, backend-bound election result signatures."""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import create_app, db
from app.models import Election, ResultSigningPublicKey, SignedElectionResult, User
from app.security import signing_service
from app.security.jwt_helpers import issue_token
from app.security.vault_client import VaultClient, VaultOperationError


def _close_test_election(app) -> int:
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election.status = "closed"
        db.session.commit()
        return election.id


def _login_manager(client):
    return client.post(
        "/login",
        data={"username": "admin", "password": "Admin@123456!"},
    )


def test_app_loads_vault_key_identity_from_environment(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "testing")
    monkeypatch.setenv("VAULT_ADDR", "https://vault.internal")
    monkeypatch.setenv("VAULT_CLUSTER_ID", "election-cluster-a")
    monkeypatch.setenv("VAULT_NAMESPACE", "securevote")
    monkeypatch.setenv("VAULT_MOUNT", "election-transit")
    monkeypatch.setenv("VAULT_TRANSIT_KEY", "custom-results-key")
    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )

    assert application.config["VAULT_ADDR"] == "https://vault.internal"
    assert application.config["VAULT_CLUSTER_ID"] == "election-cluster-a"
    assert application.config["VAULT_NAMESPACE"] == "securevote"
    assert application.config["VAULT_MOUNT"] == "election-transit"
    assert application.config["VAULT_TRANSIT_KEY"] == "custom-results-key"


def test_local_signature_records_public_key_fingerprint(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(signing_service, "_private_key", private_key)
    monkeypatch.setattr(signing_service, "_public_key", public_key)
    monkeypatch.setattr(
        signing_service,
        "vault_client",
        SimpleNamespace(
            is_configured=False,
            is_enabled=False,
            transit_signature_version=VaultClient.transit_signature_version,
        ),
    )

    expected_key_id = hashlib.sha256(
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()

    with app.app_context():
        signed = signing_service.sign_data(b"closed election result")
        assert signed.signer_backend == signing_service.LOCAL_RSA_BACKEND
        assert signed.signature_algorithm == signing_service.RSA_PSS_SHA256
        assert signed.signing_key_id == expected_key_id
        assert signed.signing_key_version is None
        assert signing_service.verify_signature(
            b"closed election result",
            signed.signature,
            signer_backend=signed.signer_backend,
            signature_algorithm=signed.signature_algorithm,
            signing_key_id=signed.signing_key_id,
            signing_key_version=signed.signing_key_version,
            public_key_pem=signed.public_key_pem,
        )


def test_vault_client_preserves_signature_envelope_and_version(monkeypatch):
    calls = {}

    class FakeTransit:
        def sign_data(self, **kwargs):
            calls["sign"] = kwargs
            return {"data": {"signature": "vault:v7:c2lnbmF0dXJl"}}

        def verify_signed_data(self, **kwargs):
            calls["verify"] = kwargs
            return {"data": {"valid": True}}

    client = VaultClient()
    client._configured = True
    client._enabled = True
    client._cluster_id = "cluster-a"
    client._namespace = "elections"
    client._client = SimpleNamespace(
        secrets=SimpleNamespace(transit=FakeTransit())
    )

    envelope = client.transit_sign("results-signing", b"payload")
    assert envelope == "vault:v7:c2lnbmF0dXJl"
    assert client.transit_signature_version(envelope) == 7
    assert client.transit_verify("results-signing", b"payload", envelope)
    assert calls["verify"]["signature"] == envelope
    assert client.transit_key_identity("results-signing") == (
        "cluster=cluster-a|namespace=elections|mount=transit|key=results-signing"
    )
    assert calls["sign"]["signature_algorithm"] == "pss"
    assert calls["verify"]["signature_algorithm"] == "pss"


def test_configured_vault_failure_never_falls_back_to_local(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FailingVault:
        is_configured = True
        is_enabled = True

        @staticmethod
        def transit_sign(_key_name, _data):
            raise VaultOperationError("Vault unavailable")

    monkeypatch.setattr(signing_service, "_private_key", private_key)
    monkeypatch.setattr(signing_service, "vault_client", FailingVault())

    with app.app_context(), pytest.raises(signing_service.SigningUnavailableError):
        signing_service.sign_data(b"must not use the local key")


def test_verification_never_crosses_signature_backends(app, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(signing_service, "_private_key", private_key)
    monkeypatch.setattr(signing_service, "_public_key", public_key)
    monkeypatch.setattr(
        signing_service,
        "vault_client",
        SimpleNamespace(
            is_configured=False,
            is_enabled=False,
            transit_signature_version=VaultClient.transit_signature_version,
        ),
    )
    local_signature = private_key.sign(
        b"payload",
        signing_service.LOCAL_RSA_PADDING,
        signing_service.LOCAL_RSA_HASH,
    ).hex()

    with app.app_context():
        assert signing_service.verify_signature(
            b"payload",
            local_signature,
            signer_backend=signing_service.VAULT_TRANSIT_BACKEND,
            signature_algorithm=signing_service.RSA_PSS_SHA256,
            signing_key_id="results-signing",
            signing_key_version=1,
        ) is False


def test_first_signature_is_immutable_and_verification_uses_stored_metadata(
    client,
    app,
    monkeypatch,
):
    election_id = _close_test_election(app)
    _login_manager(client)
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
    signed = signing_service.SigningResult(
        signature="ab12",
        signer_backend=signing_service.LOCAL_RSA_BACKEND,
        signature_algorithm=signing_service.RSA_PSS_SHA256,
        signing_key_id=key_id,
        signing_key_version=None,
        public_key_pem=public_key_pem,
    )
    sign_calls = []

    def sign_once(payload):
        sign_calls.append(payload)
        return signed

    monkeypatch.setattr("app.routes.results.signing_service.sign_data", sign_once)
    monkeypatch.setattr("app.routes.results.get_vote_tallies", lambda _id: [])

    first = client.post("/results/sign", json={"election_id": election_id})
    assert first.status_code == 200

    with app.app_context():
        stored = SignedElectionResult.query.filter_by(election_id=election_id).one()
        original = (
            stored.payload,
            stored.signature,
            stored.signed_at,
            stored.signed_by,
            stored.signer_backend,
            stored.signature_algorithm,
            stored.signing_key_id,
            stored.signing_key_version,
        )

    second = client.post("/results/sign", json={"election_id": election_id})
    assert second.status_code == 409
    assert len(sign_calls) == 1

    with app.app_context():
        stored = SignedElectionResult.query.filter_by(election_id=election_id).one()
        assert (
            stored.payload,
            stored.signature,
            stored.signed_at,
            stored.signed_by,
            stored.signer_backend,
            stored.signature_algorithm,
            stored.signing_key_id,
            stored.signing_key_version,
        ) == original

    latest = client.get(f"/results/latest?election_id={election_id}")
    assert latest.status_code == 200
    package = latest.get_json()
    assert package["signer_backend"] == signed.signer_backend
    assert package["signature_algorithm"] == signed.signature_algorithm
    assert package["signing_key_id"] == signed.signing_key_id
    assert package["signing_key_version"] is None

    verify_calls = []

    def verify_with_metadata(payload, signature, **metadata):
        verify_calls.append((payload, signature, metadata))
        return True

    monkeypatch.setattr(
        "app.routes.results.signing_service.verify_signature",
        verify_with_metadata,
    )
    verified = client.post(
        "/results/verify",
        json={"data": package["data"], "signature": package["signature"]},
    )
    assert verified.status_code == 200
    assert verified.get_json()["is_valid"] is True
    assert len(verify_calls) == 1
    assert verify_calls[0][0] == json.dumps(
        package["data"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert verify_calls[0][1] == signed.signature
    assert verify_calls[0][2] == {
        "signer_backend": signed.signer_backend,
        "signature_algorithm": signed.signature_algorithm,
        "signing_key_id": signed.signing_key_id,
        "signing_key_version": signed.signing_key_version,
        "public_key_pem": signed.public_key_pem,
    }

    tampered = dict(package["data"])
    tampered["total_votes"] = 1
    rejected = client.post(
        "/results/verify",
        json={"data": tampered, "signature": package["signature"]},
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["is_valid"] is False
    assert len(verify_calls) == 1


def test_archived_local_key_survives_runtime_key_rotation(client, app, monkeypatch):
    election_id = _close_test_election(app)
    _login_manager(client)
    key_a = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(signing_service, "_private_key", key_a)
    monkeypatch.setattr(signing_service, "_public_key", key_a.public_key())
    monkeypatch.setattr(
        signing_service,
        "vault_client",
        SimpleNamespace(is_configured=False, is_enabled=False),
    )

    signed = client.post("/results/sign", json={"election_id": election_id})
    assert signed.status_code == 200
    package = client.get(f"/results/latest?election_id={election_id}").get_json()
    assert package["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")

    key_b = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(signing_service, "_private_key", key_b)
    monkeypatch.setattr(signing_service, "_public_key", key_b.public_key())

    verified = client.post(
        "/results/verify",
        json={"data": package["data"], "signature": package["signature"]},
    )
    assert verified.status_code == 200
    assert verified.get_json()["is_valid"] is True


def test_signed_result_rejects_orm_update_and_delete(app):
    with app.app_context():
        election = Election.query.filter_by(status="open").one()
        election.status = "closed"
        stored = SignedElectionResult(
            election_id=election.id,
            payload='{"election_id":1}',
            signature="ab12",
            signer_backend=signing_service.LOCAL_RSA_BACKEND,
            signature_algorithm=signing_service.RSA_PSS_SHA256,
            signing_key_id="a" * 64,
            signing_key_version=None,
            signed_by=User.query.filter_by(username="admin").one().id,
        )
        db.session.add(stored)
        db.session.commit()

        stored.payload = '{}'
        with pytest.raises(ValueError, match="immutable"):
            db.session.commit()
        db.session.rollback()

        stored = db.session.get(SignedElectionResult, stored.id)
        db.session.delete(stored)
        with pytest.raises(ValueError, match="immutable"):
            db.session.commit()
        db.session.rollback()


def test_latest_results_fails_closed_without_local_key_archive(
    client,
    app,
    monkeypatch,
):
    election_id = _close_test_election(app)
    _login_manager(client)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(signing_service, "_private_key", private_key)
    monkeypatch.setattr(signing_service, "_public_key", private_key.public_key())
    monkeypatch.setattr(
        signing_service,
        "vault_client",
        SimpleNamespace(is_configured=False, is_enabled=False),
    )
    response = client.post("/results/sign", json={"election_id": election_id})
    assert response.status_code == 200

    with app.app_context():
        db.session.execute(db.delete(ResultSigningPublicKey))
        db.session.commit()

    latest = client.get(f"/results/latest?election_id={election_id}")
    assert latest.status_code == 503
    assert latest.get_json()["error"] == "Result signing provenance is unavailable."


def test_concurrent_result_signing_persists_and_signs_only_once(app, monkeypatch):
    election_id = _close_test_election(app)
    client_a = app.test_client()
    client_b = app.test_client()
    with app.app_context():
        manager = User.query.filter_by(username="admin").one()
        manager_token = issue_token(manager.id)
    client_a.set_cookie("session_token", manager_token)
    client_b.set_cookie("session_token", manager_token)

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
    signed = signing_service.SigningResult(
        signature="ab12",
        signer_backend=signing_service.LOCAL_RSA_BACKEND,
        signature_algorithm=signing_service.RSA_PSS_SHA256,
        signing_key_id=key_id,
        signing_key_version=None,
        public_key_pem=public_key_pem,
    )
    calls = []
    calls_lock = threading.Lock()

    def sign_once(payload):
        with calls_lock:
            calls.append(payload)
        return signed

    monkeypatch.setattr("app.routes.results.signing_service.sign_data", sign_once)
    monkeypatch.setattr("app.routes.results.get_vote_tallies", lambda _id: [])
    start = threading.Barrier(2)

    def submit(client):
        start.wait(timeout=5)
        return client.post(
            "/results/sign",
            json={"election_id": election_id},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(submit, client_a),
            pool.submit(submit, client_b),
        ]
        statuses = sorted(future.result() for future in futures)

    assert statuses == [200, 409]
    assert len(calls) == 1
    with app.app_context():
        assert SignedElectionResult.query.filter_by(election_id=election_id).count() == 1
