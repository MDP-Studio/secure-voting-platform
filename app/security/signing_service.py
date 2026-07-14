"""Election-result signing with durable signer provenance."""

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import current_app

from .vault_client import (
    InvalidVaultSignatureError,
    VaultOperationError,
    VaultUnavailableError,
    vault_client,
)


LOCAL_RSA_BACKEND = "local-rsa"
VAULT_TRANSIT_BACKEND = "vault-transit"
RSA_PSS_SHA256 = "rsa-pss-sha256"
LOCAL_RSA_HASH = hashes.SHA256()
LOCAL_RSA_PADDING = padding.PSS(
    mgf=padding.MGF1(LOCAL_RSA_HASH),
    salt_length=padding.PSS.MAX_LENGTH,
)


class SigningUnavailableError(RuntimeError):
    """Raised when the signature's selected backend cannot safely operate."""


class SignatureMetadataError(ValueError):
    """Raised when persisted signer metadata is incomplete or unsupported."""


@dataclass(frozen=True)
class SigningResult:
    """A signature plus the exact provenance required to verify it later."""

    signature: str
    signer_backend: str
    signature_algorithm: str
    signing_key_id: str
    signing_key_version: int | None
    public_key_pem: str | None = None


_private_key: rsa.RSAPrivateKey | None = None
_public_key: rsa.RSAPublicKey | None = None
_LOCAL_KEY_ID = re.compile(r"\A[0-9a-f]{64}\Z")


def _public_key_fingerprint(public_key: rsa.RSAPublicKey) -> str:
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def load_keys() -> None:
    """Load and validate the local RSA result-signing keypair."""
    global _private_key, _public_key

    instance_path = Path(current_app.instance_path)
    private_key_path = instance_path / "private_key.pem"
    public_key_path = instance_path / "public_key.pem"

    try:
        with private_key_path.open("rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
            )
        with public_key_path.open("rb") as key_file:
            public_key = serialization.load_pem_public_key(key_file.read())

        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError("The local signing private key is not RSA.")
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise ValueError("The local signing public key is not RSA.")
        if _public_key_fingerprint(private_key.public_key()) != _public_key_fingerprint(
            public_key
        ):
            raise ValueError("The local signing public and private keys do not match.")

        _private_key = private_key
        _public_key = public_key
    except (OSError, TypeError, ValueError):
        current_app.logger.error(
            "Could not load a valid local result-signing keypair.",
            exc_info=True,
        )
        _private_key = None
        _public_key = None


def _local_private_key() -> rsa.RSAPrivateKey:
    if _private_key is None:
        load_keys()
    if _private_key is None:
        raise SigningUnavailableError(
            "The local result-signing private key is unavailable."
        )
    return _private_key


def _local_public_key() -> rsa.RSAPublicKey:
    if _public_key is None:
        load_keys()
    if _public_key is None:
        raise SigningUnavailableError(
            "The local result-signing public key is unavailable."
        )
    return _public_key


def validate_local_public_key(
    public_key_pem: str,
    signing_key_id: str,
) -> rsa.RSAPublicKey:
    """Load an archived local RSA key and verify its fingerprint identity."""
    if not isinstance(public_key_pem, str) or not public_key_pem:
        raise SignatureMetadataError("The archived local RSA public key is missing.")
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise SignatureMetadataError(
            "The archived local RSA public key is invalid."
        ) from exc
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise SignatureMetadataError(
            "The archived local result-signing key is not RSA."
        )
    if _public_key_fingerprint(public_key) != signing_key_id:
        raise SignatureMetadataError(
            "The archived local key does not match its fingerprint."
        )
    return public_key


def sign_data(data: bytes) -> SigningResult:
    """Sign data once with the configured backend and return its provenance."""
    if not isinstance(data, bytes):
        raise TypeError("Result-signing data must be bytes.")

    key_name = current_app.config.get("VAULT_TRANSIT_KEY", "results-signing")
    if vault_client.is_configured:
        if not vault_client.is_enabled:
            raise SigningUnavailableError(
                "Vault result signing is configured but unavailable."
            )
        try:
            envelope = vault_client.transit_sign(key_name, data)
            key_version = vault_client.transit_signature_version(envelope)
            key_identity = vault_client.transit_key_identity(key_name)
        except (
            InvalidVaultSignatureError,
            VaultOperationError,
            VaultUnavailableError,
        ) as exc:
            raise SigningUnavailableError(
                "Vault result signing did not complete."
            ) from exc
        return SigningResult(
            signature=envelope,
            signer_backend=VAULT_TRANSIT_BACKEND,
            signature_algorithm=RSA_PSS_SHA256,
            signing_key_id=key_identity,
            signing_key_version=key_version,
        )

    private_key = _local_private_key()
    signature = private_key.sign(data, LOCAL_RSA_PADDING, LOCAL_RSA_HASH)
    return SigningResult(
        signature=signature.hex(),
        signer_backend=LOCAL_RSA_BACKEND,
        signature_algorithm=RSA_PSS_SHA256,
        signing_key_id=_public_key_fingerprint(private_key.public_key()),
        signing_key_version=None,
        public_key_pem=private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii"),
    )


def verify_signature(
    data: bytes,
    signature: str,
    *,
    signer_backend: str,
    signature_algorithm: str,
    signing_key_id: str,
    signing_key_version: int | None,
    public_key_pem: str | None = None,
) -> bool:
    """Verify using only the backend and key recorded when the result was signed."""
    if not isinstance(data, bytes) or not isinstance(signature, str):
        raise SignatureMetadataError("Signature data and encoding are invalid.")
    if signature_algorithm != RSA_PSS_SHA256:
        raise SignatureMetadataError("The signature algorithm is unsupported.")
    if not isinstance(signing_key_id, str) or not signing_key_id:
        raise SignatureMetadataError("The signing key identifier is missing.")

    if signer_backend == VAULT_TRANSIT_BACKEND:
        if (
            isinstance(signing_key_version, bool)
            or not isinstance(signing_key_version, int)
            or signing_key_version < 1
        ):
            raise SignatureMetadataError("The Vault signing key version is invalid.")
        try:
            envelope_version = vault_client.transit_signature_version(signature)
        except InvalidVaultSignatureError:
            logging.getLogger(__name__).debug(
                "Rejected malformed Vault signature envelope."
            )
            return False
        if envelope_version != signing_key_version:
            return False
        if not vault_client.is_configured or not vault_client.is_enabled:
            raise SigningUnavailableError(
                "The recorded Vault signing backend is unavailable."
            )
        key_name = current_app.config.get('VAULT_TRANSIT_KEY', 'results-signing')
        try:
            current_identity = vault_client.transit_key_identity(key_name)
        except VaultUnavailableError as exc:
            raise SigningUnavailableError(
                "The recorded Vault key identity is unavailable."
            ) from exc
        if current_identity != signing_key_id:
            raise SigningUnavailableError(
                "The recorded Vault cluster, namespace, mount, or key is unavailable."
            )
        try:
            return vault_client.transit_verify(key_name, data, signature)
        except (VaultOperationError, VaultUnavailableError) as exc:
            raise SigningUnavailableError(
                "Vault result verification did not complete."
            ) from exc

    if signer_backend == LOCAL_RSA_BACKEND:
        if signing_key_version is not None:
            raise SignatureMetadataError(
                "Local RSA signatures must not have a key version."
            )
        if not _LOCAL_KEY_ID.fullmatch(signing_key_id):
            raise SignatureMetadataError(
                "The local RSA signing key identifier is invalid."
            )
        try:
            signature_bytes = bytes.fromhex(signature)
        except ValueError:
            logging.getLogger(__name__).debug(
                "Rejected non-hex local result signature."
            )
            return False
        public_key = validate_local_public_key(public_key_pem, signing_key_id)
        try:
            public_key.verify(
                signature_bytes,
                data,
                LOCAL_RSA_PADDING,
                LOCAL_RSA_HASH,
            )
            return True
        except (InvalidSignature, ValueError):
            logging.getLogger(__name__).debug(
                "Election result signature verification failed."
            )
            return False

    raise SignatureMetadataError("The recorded signing backend is unsupported.")
