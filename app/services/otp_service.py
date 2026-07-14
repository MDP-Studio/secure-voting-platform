"""Server-side one-time-password challenge lifecycle."""

import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone

from flask import current_app

from app import db
from app.models import OtpChallenge


MAX_FAILED_ATTEMPTS = 5
VALID_PURPOSES = {"generic", "login_mfa"}


class OtpChallengeRateLimited(RuntimeError):
    """Raised when a live or locked challenge cannot be reset yet."""


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _otp_digest(challenge_id, code):
    secret_key = current_app.config.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY is required for OTP challenges")
    message = f"{challenge_id}:{code}".encode("utf-8")
    return hmac.new(
        str(secret_key).encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def issue_otp_challenge(user_id, purpose, *, ttl_seconds=300, code=None):
    """Replace a user's challenge for one purpose and return its code once."""
    if purpose not in VALID_PURPOSES:
        raise ValueError("Unsupported OTP purpose")
    if code is None:
        code = "".join(secrets.choice(string.digits) for _ in range(6))
    if len(code) != 6 or not code.isdigit():
        raise ValueError("OTP code must contain exactly six digits")

    now = _utcnow_naive()
    challenge_id = secrets.token_hex(32)
    existing = (
        db.session.query(OtpChallenge)
        .filter_by(user_id=user_id, purpose=purpose)
        .with_for_update()
        .first()
    )
    if existing is not None:
        if existing.expires_at > now and (
            existing.consumed_at is None
            or existing.failed_attempts >= MAX_FAILED_ATTEMPTS
        ):
            raise OtpChallengeRateLimited(
                "An OTP challenge is already active or temporarily locked"
            )
        db.session.delete(existing)
        db.session.flush()

    challenge = OtpChallenge(
        id=challenge_id,
        user_id=user_id,
        purpose=purpose,
        code_digest=_otp_digest(challenge_id, code),
        expires_at=now + timedelta(seconds=max(60, min(int(ttl_seconds), 900))),
        failed_attempts=0,
        created_at=now,
    )
    db.session.add(challenge)
    db.session.commit()
    return challenge_id, code


def verify_otp_challenge(challenge_id, user_id, purpose, code):
    """Atomically verify a challenge and persist every failed attempt."""
    if not challenge_id or purpose not in VALID_PURPOSES:
        return "missing"
    challenge = (
        db.session.query(OtpChallenge)
        .filter_by(id=challenge_id, user_id=user_id, purpose=purpose)
        .with_for_update()
        .first()
    )
    if challenge is None or challenge.consumed_at is not None:
        return "missing"

    now = _utcnow_naive()
    if challenge.expires_at <= now:
        challenge.consumed_at = now
        db.session.commit()
        return "expired"
    if challenge.failed_attempts >= MAX_FAILED_ATTEMPTS:
        challenge.consumed_at = now
        db.session.commit()
        return "locked"

    supplied_digest = _otp_digest(challenge.id, str(code or ""))
    if not hmac.compare_digest(supplied_digest, challenge.code_digest):
        challenge.failed_attempts += 1
        if challenge.failed_attempts >= MAX_FAILED_ATTEMPTS:
            challenge.consumed_at = now
            result = "locked"
        else:
            result = "invalid"
        db.session.commit()
        return result

    challenge.consumed_at = now
    db.session.commit()
    return "valid"
