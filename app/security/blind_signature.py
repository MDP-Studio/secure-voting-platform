"""Election-bound RSA blind-signature primitives for anonymous voting.

Each election has an immutable RSA keypair. A blind authorization issued for
one election therefore cannot be redeemed against another election's public
key. Keypair publication uses an atomic directory rename so concurrent workers
can never observe or publish a half-written pair.

Raw RSA is required for Chaum's multiplicative blinding protocol. Ballots are
mapped into the RSA group with the existing SHA-256 full-domain hash routine.
This key material is separate from election-result signing keys.
"""

import hashlib
import hmac
import json
import logging
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class BlindSigningKeyError(RuntimeError):
    """Raised when an election keypair is absent, incomplete, or invalid."""


KEY_ROOT = "blind-signing"
PRIVATE_KEY_FILE = "private.pem"
PUBLIC_KEY_FILE = "public.pem"
KEY_METADATA_FILE = "metadata.json"
KEY_ALGORITHM = "rsa-2048-fdh-sha256"

_key_cache: dict[
    tuple[str, int],
    tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
] = {}
_cache_lock = threading.RLock()


def _validated_election_id(election_id: int) -> int:
    if isinstance(election_id, bool) or not isinstance(election_id, int):
        raise TypeError("election_id must be a positive integer.")
    if election_id < 1:
        raise ValueError("election_id must be a positive integer.")
    return election_id


def _normalized_instance_path(instance_path: str | os.PathLike[str]) -> Path:
    if not isinstance(instance_path, (str, os.PathLike)):
        raise TypeError("instance_path must be a filesystem path.")
    return Path(instance_path).expanduser().resolve(strict=False)


def _cache_key(instance_path: Path, election_id: int) -> tuple[str, int]:
    return os.path.normcase(str(instance_path)), election_id


def _key_paths(
    instance_path: str | os.PathLike[str],
    election_id: int,
) -> tuple[Path, Path]:
    validated_id = _validated_election_id(election_id)
    instance = _normalized_instance_path(instance_path)
    root = instance / KEY_ROOT
    return root, root / f"election-{validated_id}"


def _public_key_fingerprint(public_key: rsa.RSAPublicKey) -> str:
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def _load_and_validate_keypair(
    key_dir: Path,
    election_id: int,
) -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    if not key_dir.exists():
        raise BlindSigningKeyError(
            f"No blind-signing keypair exists for election {election_id}."
        )
    if key_dir.is_symlink() or not key_dir.is_dir():
        raise BlindSigningKeyError(
            f"The blind-signing key path for election {election_id} is unsafe."
        )

    private_path = key_dir / PRIVATE_KEY_FILE
    public_path = key_dir / PUBLIC_KEY_FILE
    metadata_path = key_dir / KEY_METADATA_FILE
    required_paths = (private_path, public_path, metadata_path)
    if any(path.is_symlink() or not path.is_file() for path in required_paths):
        raise BlindSigningKeyError(
            f"The blind-signing keypair for election {election_id} is incomplete."
        )

    try:
        private_key = serialization.load_pem_private_key(
            private_path.read_bytes(),
            password=None,
        )
        public_key = serialization.load_pem_public_key(public_path.read_bytes())
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BlindSigningKeyError(
            f"The blind-signing keypair for election {election_id} is invalid."
        ) from exc

    if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(
        public_key,
        rsa.RSAPublicKey,
    ):
        raise BlindSigningKeyError("Blind-signing keys must be RSA keys.")

    private_public = private_key.public_key()
    fingerprint = _public_key_fingerprint(public_key)
    if (
        private_key.key_size != 2048
        or public_key.key_size != 2048
        or private_public.public_numbers() != public_key.public_numbers()
        or public_key.public_numbers().e != 65537
    ):
        raise BlindSigningKeyError(
            f"The blind-signing keypair for election {election_id} failed validation."
        )

    if not isinstance(metadata, dict) or metadata != {
        "algorithm": KEY_ALGORITHM,
        "election_id": election_id,
        "public_key_sha256": fingerprint,
    }:
        raise BlindSigningKeyError(
            f"The blind-signing metadata for election {election_id} is invalid."
        )

    return private_key, public_key


def _write_new_file(path: Path, contents: bytes, mode: int) -> None:
    with path.open("xb") as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        path.chmod(mode)
    except OSError:
        # Windows ACLs may not map POSIX modes exactly. Exclusive creation and
        # the enclosing instance-directory ACL remain the primary controls.
        logging.getLogger(__name__).debug(
            "Could not apply POSIX mode to %s; retaining platform ACLs.",
            path,
            exc_info=True,
        )


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        logging.getLogger(__name__).debug(
            "Directory fsync is unavailable for %s.",
            path,
            exc_info=True,
        )
        return
    try:
        os.fsync(descriptor)
    except OSError:
        logging.getLogger(__name__).debug(
            "Directory fsync failed for %s.",
            path,
            exc_info=True,
        )
    finally:
        os.close(descriptor)


def generate_blind_signing_keypair(
    instance_path: str | os.PathLike[str],
    election_id: int,
) -> None:
    """Create one immutable RSA keypair for an election if none exists."""
    validated_id = _validated_election_id(election_id)
    instance = _normalized_instance_path(instance_path)
    cache_key = _cache_key(instance, validated_id)

    with _cache_lock:
        if cache_key in _key_cache:
            return

        key_root, key_dir = _key_paths(instance, validated_id)
        if key_dir.exists():
            _key_cache[cache_key] = _load_and_validate_keypair(
                key_dir,
                validated_id,
            )
            return

        try:
            key_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BlindSigningKeyError(
                "Could not create the blind-signing key directory."
            ) from exc
        if key_root.is_symlink() or not key_root.is_dir():
            raise BlindSigningKeyError("The blind-signing key root is unsafe.")

        try:
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            public_key = private_key.public_key()
            private_pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            public_pem = public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            metadata = json.dumps(
                {
                    "algorithm": KEY_ALGORITHM,
                    "election_id": validated_id,
                    "public_key_sha256": _public_key_fingerprint(public_key),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise BlindSigningKeyError(
                f"Could not generate a keypair for election {validated_id}."
            ) from exc

        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix=f".election-{validated_id}.tmp-",
                dir=key_root,
            )
        )
        try:
            _write_new_file(temporary_dir / PRIVATE_KEY_FILE, private_pem, 0o600)
            _write_new_file(temporary_dir / PUBLIC_KEY_FILE, public_pem, 0o644)
            _write_new_file(temporary_dir / KEY_METADATA_FILE, metadata, 0o644)
            _fsync_directory(temporary_dir)
            try:
                temporary_dir.rename(key_dir)
            except OSError as exc:
                # Another process may have atomically published the same
                # election keypair first. Its completed pair is authoritative.
                if not key_dir.exists():
                    raise BlindSigningKeyError(
                        f"Could not publish the keypair for election {validated_id}."
                    ) from exc
            _fsync_directory(key_root)
        finally:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)

        _key_cache[cache_key] = _load_and_validate_keypair(
            key_dir,
            validated_id,
        )


def _load_keys(
    instance_path: str | os.PathLike[str],
    election_id: int,
) -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    validated_id = _validated_election_id(election_id)
    instance = _normalized_instance_path(instance_path)
    cache_key = _cache_key(instance, validated_id)
    with _cache_lock:
        cached = _key_cache.get(cache_key)
        if cached is not None:
            return cached
        _, key_dir = _key_paths(instance, validated_id)
        loaded = _load_and_validate_keypair(key_dir, validated_id)
        _key_cache[cache_key] = loaded
        return loaded


def get_public_key_components(
    instance_path: str | os.PathLike[str],
    election_id: int,
) -> dict[str, str]:
    """Return the election's RSA modulus and exponent as hex strings."""
    _, public_key = _load_keys(instance_path, election_id)
    numbers = public_key.public_numbers()
    return {
        "n": hex(numbers.n),
        "e": hex(numbers.e),
        "key_id": _public_key_fingerprint(public_key),
    }


def ensure_election_blind_signing_key(
    instance_path: str | os.PathLike[str],
    election_id: int,
    expected_key_id: str | None,
    *,
    allow_create: bool = False,
) -> dict[str, str]:
    """Load and validate an election key against its durable DB anchor.

    Creation is allowed only while an election is being provisioned. Once a
    fingerprint is anchored, missing or replaced files fail closed instead of
    silently rotating authorizations held by voters.
    """
    if expected_key_id is None:
        if not allow_create:
            raise BlindSigningKeyError(
                "The election has no anchored blind-signing key."
            )
        generate_blind_signing_keypair(instance_path, election_id)
    elif (
        not isinstance(expected_key_id, str)
        or len(expected_key_id) != 64
        or any(character not in "0123456789abcdef" for character in expected_key_id)
    ):
        raise BlindSigningKeyError(
            "The election blind-signing key fingerprint is invalid."
        )

    components = get_public_key_components(instance_path, election_id)
    if expected_key_id is not None and not hmac.compare_digest(
        components["key_id"],
        expected_key_id,
    ):
        raise BlindSigningKeyError(
            "The election blind-signing key does not match its durable fingerprint."
        )
    return components


def hash_ballot(ballot_bytes: bytes, n: int) -> int:
    """Map ballot bytes to an RSA-domain integer using SHA-256 counter FDH."""
    if not isinstance(ballot_bytes, bytes):
        raise TypeError("ballot_bytes must be bytes.")
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        raise ValueError("n must be a valid RSA modulus.")

    seed = hashlib.sha256(ballot_bytes).digest()
    expanded = b"".join(
        hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for counter in range(8)
    )
    return int.from_bytes(expanded, "big") % n


def blind_sign(
    blinded_message_int: int,
    instance_path: str | os.PathLike[str],
    election_id: int,
) -> int:
    """Sign a blinded RSA-domain integer with the election's private key."""
    private_key, _ = _load_keys(instance_path, election_id)
    numbers = private_key.private_numbers()
    modulus = numbers.public_numbers.n
    if (
        isinstance(blinded_message_int, bool)
        or not isinstance(blinded_message_int, int)
        or not 0 < blinded_message_int < modulus
        or math.gcd(blinded_message_int, modulus) != 1
    ):
        raise ValueError("The blinded ballot is outside the election key domain.")
    return pow(blinded_message_int, numbers.d, modulus)


def verify_unblinded_signature(
    ballot_bytes: bytes,
    signature_int: int,
    instance_path: str | os.PathLike[str],
    election_id: int,
) -> bool:
    """Verify an authorization only with the named election's public key."""
    _, public_key = _load_keys(instance_path, election_id)
    numbers = public_key.public_numbers()
    if (
        isinstance(signature_int, bool)
        or not isinstance(signature_int, int)
        or not 0 < signature_int < numbers.n
    ):
        return False
    expected = hash_ballot(ballot_bytes, numbers.n)
    recovered = pow(signature_int, numbers.e, numbers.n)
    return recovered == expected
