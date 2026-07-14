import os
import base64
import binascii
import logging
import re


class VaultUnavailableError(RuntimeError):
    """Raised when Vault was selected but is not ready for an operation."""


class VaultOperationError(RuntimeError):
    """Raised when an enabled Vault backend cannot complete an operation."""


class InvalidVaultSignatureError(ValueError):
    """Raised when a Transit signature is not a complete Vault envelope."""


class VaultClient:
    """Thin wrapper around HashiCorp Vault (hvac) used optionally if configured.

    Transit operations raise when Vault is selected but unavailable so callers
    cannot silently cross from a Vault signing identity to a local key. KV reads
    retain their optional, fail-soft behaviour.
    """

    _TRANSIT_SIGNATURE = re.compile(
        r"\Avault:v(?P<version>[1-9][0-9]*):(?P<signature>[A-Za-z0-9+/]+={0,2})\Z"
    )

    def __init__(self):
        self._configured = False
        self._enabled = False
        self._client = None
        self._mount = os.environ.get('VAULT_MOUNT', 'transit')
        self._kv_mount = os.environ.get('VAULT_KV_MOUNT', 'kv')
        self._cluster_id = os.environ.get('VAULT_CLUSTER_ID')
        self._namespace = os.environ.get('VAULT_NAMESPACE', '')

        url = os.environ.get('VAULT_ADDR')
        token = os.environ.get('VAULT_TOKEN')
        token_file = os.environ.get('VAULT_TOKEN_FILE')
        self._configured = bool(url or token or token_file or self._cluster_id)

        if token and token_file:
            logging.warning(
                'Both VAULT_TOKEN and VAULT_TOKEN_FILE are set; refusing '
                'ambiguous Vault credentials.'
            )
            return
        if token_file:
            try:
                if not os.path.isfile(token_file):
                    raise OSError('token path is not a regular file')
                if os.path.getsize(token_file) > 4096:
                    raise OSError('token file is unexpectedly large')
                with open(token_file, 'r', encoding='utf-8') as handle:
                    token = handle.read().strip()
                if not token:
                    raise OSError('token file is empty')
            except OSError as exc:
                logging.warning('Vault token file is unavailable: %s', exc)
                return

        if not (url and token and self._cluster_id):
            if self._configured:
                logging.warning(
                    'Vault configuration is incomplete; VAULT_ADDR, a token '
                    'source, and VAULT_CLUSTER_ID are required.'
                )
            return

        try:
            import hvac  # type: ignore
        except Exception:
            logging.warning('Vault is configured but hvac is not installed. Skipping Vault integration.')
            return

        try:
            client = hvac.Client(
                url=url,
                token=token,
                namespace=self._namespace or None,
            )
            if client.is_authenticated():
                self._client = client
                self._enabled = True
            else:
                logging.warning('Vault token not authenticated. Skipping Vault integration.')
        except Exception as e:
            logging.warning(f'Vault client initialization failed: {e}')

    @property
    def is_enabled(self) -> bool:
        return bool(self._enabled and self._client)

    @property
    def is_configured(self) -> bool:
        """Return whether the environment selected Vault as a backend."""
        return self._configured

    @classmethod
    def transit_signature_version(cls, signature: str) -> int:
        """Validate a complete Transit signature envelope and return its version."""
        if not isinstance(signature, str):
            raise InvalidVaultSignatureError("Vault signature must be text.")
        match = cls._TRANSIT_SIGNATURE.fullmatch(signature)
        if not match:
            raise InvalidVaultSignatureError(
                "Vault signature must use the complete vault:vN:BASE64 envelope."
            )
        try:
            base64.b64decode(match.group("signature"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise InvalidVaultSignatureError(
                "Vault signature contains invalid base64 data."
            ) from exc
        return int(match.group("version"))

    def transit_key_identity(self, key_name: str) -> str:
        """Return stable, non-secret Vault key provenance for persisted results."""
        components = {
            "cluster": self._cluster_id,
            "namespace": self._namespace or "root",
            "mount": self._mount,
            "key": key_name,
        }
        for label, value in components.items():
            if (
                not isinstance(value, str)
                or not value
                or "|" in value
                or "=" in value
            ):
                raise VaultUnavailableError(
                    f"Vault {label} is missing or contains unsupported characters."
                )
        identity = "|".join(
            f"{label}={value}" for label, value in components.items()
        )
        if len(identity) > 255:
            raise VaultUnavailableError("Vault key identity exceeds 255 characters.")
        return identity

    # -------- Transit (sign/verify) --------
    def transit_sign(self, key_name: str, data: bytes) -> str:
        if not self.is_enabled:
            raise VaultUnavailableError(
                "Vault Transit signing is configured but unavailable."
            )
        try:
            b64 = base64.b64encode(data).decode('ascii')
            resp = self._client.secrets.transit.sign_data(
                name=key_name,
                hash_algorithm='sha2-256',
                signature_algorithm='pss',
                salt_length='auto',
                input=b64,
                mount_point=self._mount,
            )
            # Preserve the complete envelope. Its version is part of the
            # cryptographic identity and is required after Transit key rotation.
            sig = resp['data']['signature']
            self.transit_signature_version(sig)
            return sig
        except Exception as e:
            logging.error('Vault Transit signing failed.', exc_info=True)
            raise VaultOperationError("Vault Transit signing failed.") from e

    def transit_verify(self, key_name: str, data: bytes, signature: str) -> bool:
        if not self.is_enabled:
            raise VaultUnavailableError(
                "Vault Transit verification is configured but unavailable."
            )
        self.transit_signature_version(signature)
        try:
            data_b64 = base64.b64encode(data).decode('ascii')
            resp = self._client.secrets.transit.verify_signed_data(
                name=key_name,
                hash_algorithm='sha2-256',
                signature_algorithm='pss',
                salt_length='auto',
                input=data_b64,
                signature=signature,
                mount_point=self._mount,
            )
            return bool(resp['data'].get('valid'))
        except Exception as e:
            logging.error('Vault Transit verification failed.', exc_info=True)
            raise VaultOperationError("Vault Transit verification failed.") from e

    # -------- KV (secrets) --------
    def kv_get(self, path: str, key: str) -> str | None:
        if not self.is_enabled:
            return None
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._kv_mount,
            )
            return resp['data']['data'].get(key)
        except Exception as e:
            logging.warning(f'Vault KV read failed for {path}:{key}: {e}')
            return None


vault_client = VaultClient()


