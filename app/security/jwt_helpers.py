import os
import time
from typing import Optional
import jwt

# Small wrapper around PyJWT for issuing and verifying access tokens

SECRET = os.environ.get('SECRET_KEY', 'dev-secret')
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
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None
