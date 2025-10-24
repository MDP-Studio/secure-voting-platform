import os
import time
from typing import Optional
import jwt
from flask import current_app
from .vault_client import vault_client

# Small wrapper around PyJWT for issuing and verifying access tokens

def _get_secret() -> str:
    # Prefer Vault KV if available
    if vault_client.is_enabled:
        path = current_app.config.get('VAULT_JWT_PATH', 'app/jwt')
        key = current_app.config.get('VAULT_JWT_KEY', 'secret')
        val = vault_client.kv_get(path, key)
        if val:
            return val
    return os.environ.get('SECRET_KEY', 'dev-secret')
ALGORITHM = 'HS256'
# token lifetime in seconds (15 minutes)
TOKEN_LIFETIME = int(os.environ.get('JWT_LIFETIME_SECONDS', 15 * 60))


def issue_token(user_id: int) -> str:
    now = int(time.time())
    payload = {
        'sub': str(user_id),
        'iat': now,
        'exp': now + TOKEN_LIFETIME,
    }
    secret = _get_secret()
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        secret = _get_secret()
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None
