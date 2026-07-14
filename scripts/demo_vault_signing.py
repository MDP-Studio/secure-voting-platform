#!/usr/bin/env python3
"""Demonstrate result signing with explicitly configured Vault credentials."""

import json
import os
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _require_vault_configuration():
    required = ("VAULT_ADDR", "VAULT_CLUSTER_ID", "VAULT_MOUNT", "VAULT_TRANSIT_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if not (os.environ.get("VAULT_TOKEN") or os.environ.get("VAULT_TOKEN_FILE")):
        missing.append("VAULT_TOKEN or VAULT_TOKEN_FILE")
    if missing:
        raise RuntimeError("Missing Vault configuration: " + ", ".join(missing))


def _verify(application, data, signed):
    from app.security.signing_service import verify_signature

    with application.app_context():
        return verify_signature(
            data,
            signed.signature,
            signer_backend=signed.signer_backend,
            signature_algorithm=signed.signature_algorithm,
            signing_key_id=signed.signing_key_id,
            signing_key_version=signed.signing_key_version,
            public_key_pem=signed.public_key_pem,
        )


def demo_result_signing():
    _require_vault_configuration()
    from app import create_app
    from app.security.signing_service import sign_data
    from app.security.vault_client import vault_client

    if not vault_client.is_enabled:
        print("Vault is selected but unavailable. Signing correctly fails closed.")
        return False

    results = {
        "election_id": 2024,
        "timestamp": int(time.time()),
        "results": {"candidate_1": 1250, "candidate_2": 980},
        "total_votes": 2230,
    }
    data = json.dumps(results, sort_keys=True, separators=(",", ":")).encode()
    application = create_app()
    with application.app_context():
        signed = sign_data(data)

    print(f"Signed with {signed.signer_backend}: {signed.signing_key_id}")
    if not _verify(application, data, signed):
        print("Signature verification failed.")
        return False

    tampered = data.replace(b"1250", b"9999")
    if _verify(application, tampered, signed):
        print("Tamper detection failed.")
        return False

    print("Signing, verification, and tamper detection passed.")
    return True


if __name__ == "__main__":
    try:
        passed = demo_result_signing()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        passed = False
    raise SystemExit(0 if passed else 1)
