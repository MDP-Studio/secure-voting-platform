"""Versioned, authenticated encryption for voter PII.

Runtime reads accept only the current, explicitly versioned envelope. Legacy
values must be converted through one of the explicit migration helpers before
the application will expose them as plaintext.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from flask import current_app
from sqlalchemy.types import String, TypeDecorator


class PIIDecryptionError(RuntimeError):
    """Raised when stored PII cannot be authenticated and decrypted."""


class LegacyPIIMigrationError(ValueError):
    """Raised when an explicitly requested legacy conversion is invalid."""


class ChaChaEncryptionService:
    """Encrypt and decrypt PII using a versioned ChaCha20-Poly1305 envelope."""

    _instance = None
    _key = None

    ENVELOPE_PREFIX = "svpii:v1:"
    LEGACY_PLAINTEXT_PREFIX = "svpii:legacy-plaintext:v0:"
    ASSOCIATED_DATA = b"securevote:voter-pii:v1"
    NONCE_BYTES = 12
    TAG_BYTES = 16

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls, key=None):
        """Initialize the process-wide service with one 32-byte Base64 key."""
        if key is None:
            key = os.environ.get("VOTER_PII_KEY_BASE64")
            if not key:
                raise RuntimeError("VOTER_PII_KEY_BASE64 environment variable not set")

        if isinstance(key, str):
            try:
                key = base64.b64decode(key, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("Invalid Base64 PII encryption key") from exc

        if not isinstance(key, bytes) or len(key) != 32:
            raise RuntimeError("ChaCha20Poly1305 requires a 32-byte key")

        cls._key = key
        cls._instance = cls()
        return cls._instance

    def __init__(self):
        if self._key is None:
            raise RuntimeError(
                "ChaChaEncryptionService not initialized. Call initialize() first."
            )
        self.cipher = ChaCha20Poly1305(self._key)

    @classmethod
    def _decode_payload(cls, payload: str) -> bytes:
        """Strictly decode an AEAD payload without normalizing attacker input."""
        if not isinstance(payload, str) or not payload:
            raise PIIDecryptionError("Stored PII envelope has no ciphertext payload")
        if payload != payload.strip() or len(payload) % 4 != 0:
            raise PIIDecryptionError("Stored PII envelope has invalid Base64 framing")
        try:
            combined = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PIIDecryptionError(
                "Stored PII envelope has invalid Base64 framing"
            ) from exc
        if len(combined) < cls.NONCE_BYTES + cls.TAG_BYTES:
            raise PIIDecryptionError("Stored PII envelope is truncated")
        return combined

    def _decrypt_combined(self, combined: bytes, associated_data: bytes | None) -> str:
        nonce = combined[: self.NONCE_BYTES]
        ciphertext = combined[self.NONCE_BYTES :]
        try:
            plaintext = self.cipher.decrypt(nonce, ciphertext, associated_data)
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise PIIDecryptionError(
                "Stored PII failed authenticated decryption"
            ) from exc

    def encrypt(self, data: str) -> str:
        """Encrypt a value into the current authenticated envelope."""
        if data is None:
            return None
        if not isinstance(data, str):
            data = str(data)

        nonce = os.urandom(self.NONCE_BYTES)
        try:
            ciphertext = self.cipher.encrypt(
                nonce,
                data.encode("utf-8"),
                self.ASSOCIATED_DATA,
            )
        except Exception as exc:
            current_app.logger.exception("PII encryption failed")
            raise RuntimeError("Failed to encrypt PII") from exc

        payload = base64.b64encode(nonce + ciphertext).decode("ascii")
        return f"{self.ENVELOPE_PREFIX}{payload}"

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt current-format PII, failing closed on every invalid value."""
        if encrypted_data is None:
            return None
        if not isinstance(encrypted_data, str):
            raise PIIDecryptionError("Stored PII envelope must be text")
        if not encrypted_data.startswith(self.ENVELOPE_PREFIX):
            raise PIIDecryptionError(
                "Stored PII has no supported version marker; run the explicit migration"
            )

        payload = encrypted_data[len(self.ENVELOPE_PREFIX) :]
        combined = self._decode_payload(payload)
        return self._decrypt_combined(combined, self.ASSOCIATED_DATA)

    def migrate_legacy_plaintext(self, marked_value: str) -> str:
        """Encrypt plaintext only when an operator supplied the legacy marker.

        The normal decrypt path intentionally rejects this marker. A migration
        must first mark reviewed plaintext values and then call this method.
        """
        if not isinstance(marked_value, str) or not marked_value.startswith(
            self.LEGACY_PLAINTEXT_PREFIX
        ):
            raise LegacyPIIMigrationError(
                "Legacy plaintext must carry the explicit legacy-plaintext marker"
            )
        plaintext = marked_value[len(self.LEGACY_PLAINTEXT_PREFIX) :]
        return self.encrypt(plaintext)

    def migrate_legacy_ciphertext(self, unversioned_ciphertext: str) -> str:
        """Authenticate old unversioned ChaCha ciphertext and re-encrypt as v1.

        This method is deliberately separate from runtime decryption so an
        unversioned or tampered database value can never be mistaken for text.
        """
        if not isinstance(unversioned_ciphertext, str):
            raise LegacyPIIMigrationError("Legacy ciphertext must be text")
        if unversioned_ciphertext.startswith(self.ENVELOPE_PREFIX):
            raise LegacyPIIMigrationError("Value is already current-format PII")
        try:
            combined = self._decode_payload(unversioned_ciphertext)
            plaintext = self._decrypt_combined(combined, None)
        except PIIDecryptionError as exc:
            raise LegacyPIIMigrationError(
                "Legacy ciphertext failed authenticated decryption"
            ) from exc
        return self.encrypt(plaintext)


class EncryptedType(TypeDecorator):
    """SQLAlchemy type that fails closed when stored PII is not authentic."""

    impl = String
    cache_ok = True

    def __init__(self, length=None):
        super().__init__(length=length)
        self.length = length
        # prefix + Base64(12-byte nonce + 16-byte tag + one-byte plaintext)
        self.min_length = len(ChaChaEncryptionService.ENVELOPE_PREFIX) + 40
        if length is not None and length < self.min_length:
            raise ValueError(
                f"Column length must be at least {self.min_length} characters"
            )

    @staticmethod
    def _service() -> ChaChaEncryptionService:
        """Resolve the current process-wide key without caching stale instances."""
        try:
            return ChaChaEncryptionService.get_instance()
        except RuntimeError:
            key_b64 = os.environ.get("VOTER_PII_KEY_BASE64")
            if not key_b64:
                raise
            return ChaChaEncryptionService.initialize(key_b64)

    def process_bind_param(self, value, dialect):
        """Encrypt plaintext before saving it to the database."""
        if value is None:
            return None
        encrypted = self._service().encrypt(value)
        if self.length and len(encrypted) > self.length:
            raise ValueError(
                f"Encrypted value length ({len(encrypted)}) exceeds column length "
                f"({self.length})"
            )
        return encrypted

    def process_result_value(self, value, dialect):
        """Authenticate and decrypt a database value without plaintext fallback."""
        if value is None:
            return None
        return self._service().decrypt(value)
