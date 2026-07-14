import logging
import os
import time
from typing import Optional
import jwt
from flask import current_app, has_app_context

# Small wrapper around PyJWT for issuing and verifying access tokens

def _get_secret() -> str:
    # JWTs have one stable source. Vault Transit is scoped to result signing
    # and must never cause implicit KV calls or session-key source switching.
    if has_app_context():
        configured_secret = current_app.config.get('SECRET_KEY')
        if configured_secret:
            return configured_secret
    environment_secret = os.environ.get('SECRET_KEY')
    if environment_secret:
        return environment_secret
    raise RuntimeError("SECRET_KEY is required for JWT operations")
ALGORITHM = 'HS256'
# token lifetime in seconds (15 minutes)
TOKEN_LIFETIME = int(os.environ.get('JWT_LIFETIME_SECONDS', 15 * 60))


def issue_token(user_id: int, session_version: int | None = None) -> str:
    if session_version is None:
        # Resolve the durable epoch at issuance so callers cannot accidentally
        # create a token that survives a password change.
        from app import db
        from app.models import User

        user = db.session.get(User, int(user_id))
        if user is None:
            raise RuntimeError("Cannot issue a session for an unknown user")
        session_version = user.session_version
    if isinstance(session_version, bool) or not isinstance(session_version, int):
        raise RuntimeError("User session version is invalid")

    now = int(time.time())
    payload = {
        'sub': str(user_id),
        'iat': now,
        'exp': now + TOKEN_LIFETIME,
        'ver': session_version,
    }
    secret = _get_secret()
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        secret = _get_secret()
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "iat", "exp", "ver"]},
        )
        return payload
    except Exception:
        logging.getLogger(__name__).debug("Handled exception in app/security/jwt_helpers.py", exc_info=True)
        return None
