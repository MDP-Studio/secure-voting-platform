"""
RSA Blind Signature primitives for anonymous voting.

Implements the Chaum blind signature protocol (1983) with Full-Domain
Hash (FDH) as proven secure by Bellare & Rogaway (1996).

Protocol overview:
  1. Voter blinds ballot:      blinded = hash(ballot) * r^e mod n
  2. Server signs blind data:  blind_sig = blinded^d mod n
  3. Voter unblinds:           sig = blind_sig * r^(-1) mod n
  4. Anyone can verify:        sig^e mod n == hash(ballot)

The server never sees the unblinded ballot — it signs a random-looking
integer and has no way to correlate it with the final ballot.

IMPORTANT: This uses a SEPARATE keypair from result signing.
Raw RSA (no padding) is required for the multiplicative homomorphism
that makes blinding work. FDH provides the security proof.
"""

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Cache loaded keys in module scope
_private_key = None
_public_key = None

PRIVATE_KEY_FILE = "blind_sig_private.pem"
PUBLIC_KEY_FILE = "blind_sig_public.pem"


def generate_blind_signing_keypair(instance_path: str) -> None:
    """Generate a 2048-bit RSA keypair for blind signing. No-op if exists."""
    path = Path(instance_path)
    priv_path = path / PRIVATE_KEY_FILE
    pub_path = path / PUBLIC_KEY_FILE

    if priv_path.exists() and pub_path.exists():
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    os.makedirs(instance_path, exist_ok=True)
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)


def _load_keys(instance_path: str):
    """Load and cache the blind-signing RSA keypair."""
    global _private_key, _public_key
    if _private_key and _public_key:
        return _private_key, _public_key

    path = Path(instance_path)
    priv_pem = (path / PRIVATE_KEY_FILE).read_bytes()
    pub_pem = (path / PUBLIC_KEY_FILE).read_bytes()

    _private_key = serialization.load_pem_private_key(priv_pem, password=None)
    _public_key = serialization.load_pem_public_key(pub_pem)
    return _private_key, _public_key


def get_public_key_components(instance_path: str) -> dict:
    """Return {n, e} as hex strings for client-side blinding."""
    _, pub = _load_keys(instance_path)
    nums = pub.public_numbers()
    return {"n": hex(nums.n), "e": hex(nums.e)}


def hash_ballot(ballot_bytes: bytes, n: int) -> int:
    """
    Full-Domain Hash (FDH) — map ballot bytes to an element of Z_n.

    Uses SHA-256 in counter mode to produce enough bytes to fill the
    RSA modulus space, then reduces mod n. This construction is
    provably secure for RSA blind signatures (Bellare-Rogaway 1996).

    The client-side JavaScript MUST replicate this exactly:
      1. seed = SHA-256(ballot_bytes)
      2. For i in 0..7: blocks[i] = SHA-256(seed || i as 4-byte big-endian)
      3. expanded = concat(blocks)  (256 bytes)
      4. result = int(expanded) mod n
    """
    seed = hashlib.sha256(ballot_bytes).digest()
    expanded = b""
    for i in range(8):
        expanded += hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
    return int.from_bytes(expanded, "big") % n


def blind_sign(blinded_message_int: int, instance_path: str) -> int:
    """
    Sign a blinded message using raw RSA: sig = m^d mod n.

    The server sees only a random-looking integer (the blinded ballot).
    It cannot determine the actual ballot contents.
    """
    priv, _ = _load_keys(instance_path)
    priv_nums = priv.private_numbers()
    d = priv_nums.d
    n = priv_nums.public_numbers.n
    return pow(blinded_message_int, d, n)


def verify_unblinded_signature(ballot_bytes: bytes, signature_int: int,
                                instance_path: str) -> bool:
    """
    Verify an unblinded signature: sig^e mod n == FDH(ballot).

    This proves the ballot was signed by the authority (proving voter
    eligibility) without revealing which voter requested the signature.
    """
    _, pub = _load_keys(instance_path)
    nums = pub.public_numbers()
    n = nums.n
    e = nums.e

    expected = hash_ballot(ballot_bytes, n)
    recovered = pow(signature_int, e, n)
    return recovered == expected
