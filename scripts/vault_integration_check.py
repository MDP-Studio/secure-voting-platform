#!/usr/bin/env python3
"""Check an explicitly configured Vault and SecureVote signing integration."""

import base64
import os
import sys
from pathlib import Path

import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _read_token():
    token = os.environ.get("VAULT_TOKEN")
    token_file = os.environ.get("VAULT_TOKEN_FILE")
    if token and token_file:
        raise RuntimeError("Set only one of VAULT_TOKEN or VAULT_TOKEN_FILE")
    if token:
        return token
    if token_file:
        path = Path(token_file)
        if not path.is_file() or path.stat().st_size > 4096:
            raise RuntimeError("VAULT_TOKEN_FILE is missing or invalid")
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise RuntimeError("VAULT_TOKEN or VAULT_TOKEN_FILE is required")


def _require_vault_configuration():
    required = ("VAULT_ADDR", "VAULT_CLUSTER_ID", "VAULT_MOUNT", "VAULT_TRANSIT_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing Vault configuration: " + ", ".join(missing))
    _read_token()


def test_vault_connectivity():
    try:
        response = requests.get(
            os.environ["VAULT_ADDR"].rstrip("/") + "/v1/sys/health",
            timeout=5,
        )
        return response.status_code in {200, 429, 472, 473}
    except requests.RequestException as exc:
        print(f"Vault health request failed: {exc}", file=sys.stderr)
        return False


def test_transit_engine():
    try:
        import hvac

        client = hvac.Client(
            url=os.environ["VAULT_ADDR"],
            token=_read_token(),
            namespace=os.environ.get("VAULT_NAMESPACE") or None,
        )
        if not client.is_authenticated():
            return False
        data = b"securevote transit integration check"
        encoded = base64.b64encode(data).decode("ascii")
        signed = client.secrets.transit.sign_data(
            name=os.environ["VAULT_TRANSIT_KEY"],
            input=encoded,
            hash_algorithm="sha2-256",
            signature_algorithm="pss",
            salt_length="auto",
            mount_point=os.environ["VAULT_MOUNT"],
        )
        envelope = signed["data"]["signature"]
        verified = client.secrets.transit.verify_signed_data(
            name=os.environ["VAULT_TRANSIT_KEY"],
            input=encoded,
            signature=envelope,
            hash_algorithm="sha2-256",
            signature_algorithm="pss",
            salt_length="auto",
            mount_point=os.environ["VAULT_MOUNT"],
        )
        return bool(verified["data"].get("valid"))
    except Exception as exc:
        print(f"Vault Transit check failed: {exc}", file=sys.stderr)
        return False


def test_voting_integration():
    try:
        from app import create_app
        from app.security.signing_service import sign_data, verify_signature
        from app.security.vault_client import vault_client

        if not vault_client.is_enabled:
            return False
        application = create_app()
        data = b"election results integration check"
        with application.app_context():
            signed = sign_data(data)
            return verify_signature(
                data,
                signed.signature,
                signer_backend=signed.signer_backend,
                signature_algorithm=signed.signature_algorithm,
                signing_key_id=signed.signing_key_id,
                signing_key_version=signed.signing_key_version,
                public_key_pem=signed.public_key_pem,
            )
    except Exception as exc:
        print(f"SecureVote Vault integration failed: {exc}", file=sys.stderr)
        return False


def main():
    try:
        _require_vault_configuration()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    checks = {
        "Vault health": test_vault_connectivity(),
        "Transit sign/verify": test_transit_engine(),
        "SecureVote signing API": test_voting_integration(),
    }
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
