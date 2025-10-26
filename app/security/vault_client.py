import os
import base64
import logging


class VaultClient:
    """Thin wrapper around HashiCorp Vault (hvac) used optionally if configured.

    This client fails closed (i.e., returns None/False) and never raises if Vault
    is not configured or the hvac library is missing. Callers must provide
    secure fallbacks (local keys/env secrets).
    """

    def __init__(self):
        self._enabled = False
        self._client = None
        self._mount = os.environ.get('VAULT_MOUNT', 'transit')
        self._kv_mount = os.environ.get('VAULT_KV_MOUNT', 'kv')

        url = os.environ.get('VAULT_ADDR')
        token = os.environ.get('VAULT_TOKEN')

        if not (url and token):
            return

        try:
            import hvac  # type: ignore
        except Exception:
            logging.warning('Vault is configured but hvac is not installed. Skipping Vault integration.')
            return

        try:
            client = hvac.Client(url=url, token=token)
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

    # -------- Transit (sign/verify) --------
    def transit_sign(self, key_name: str, data: bytes) -> bytes | None:
        if not self.is_enabled:
            return None
        try:
            b64 = base64.b64encode(data).decode('ascii')
            resp = self._client.secrets.transit.sign_data(
                name=key_name,
                hash_algorithm='sha2-256',
                input=b64,
                mount_point=self._mount,
            )
            # Vault returns signature like 'vault:v1:BASE64'
            sig = resp['data']['signature']
            parts = sig.split(':')
            sig_b64 = parts[-1]
            return base64.b64decode(sig_b64)
        except Exception as e:
            logging.warning(f'Vault transit sign failed: {e}')
            return None

    def transit_verify(self, key_name: str, data: bytes, signature: bytes) -> bool:
        if not self.is_enabled:
            return False
        try:
            data_b64 = base64.b64encode(data).decode('ascii')
            sig_b64 = base64.b64encode(signature).decode('ascii')
            resp = self._client.secrets.transit.verify_signed_data(
                name=key_name,
                hash_algorithm='sha2-256',
                input=data_b64,
                signature=f'vault:v1:{sig_b64}',
                mount_point=self._mount,
            )
            return bool(resp['data'].get('valid'))
        except Exception as e:
            logging.warning(f'Vault transit verify failed: {e}')
            return False

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


