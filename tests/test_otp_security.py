"""Server-side OTP expiry, replay, and attempt-limit tests."""

from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.models import OtpChallenge, User
from app.services.otp_service import (
    OtpChallengeRateLimited,
    issue_otp_challenge,
    verify_otp_challenge,
)


def _seed_otp(app, code, *, expired=False, attempts=0):
    with app.app_context():
        user_id = User.query.filter_by(username="voter1").one().id
        challenge_id, _ = issue_otp_challenge(
            user_id,
            "generic",
            code=code,
        )
        challenge = db.session.get(OtpChallenge, challenge_id)
        if expired:
            challenge.expires_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=1)
            )
        challenge.failed_attempts = attempts
        db.session.commit()
        return user_id, challenge_id


def test_valid_otp_is_single_use(app):
    user_id, challenge_id = _seed_otp(app, "042891")

    with app.app_context():
        assert verify_otp_challenge(
            challenge_id,
            user_id,
            "generic",
            "042891",
        ) == "valid"
        assert verify_otp_challenge(
            challenge_id,
            user_id,
            "generic",
            "042891",
        ) == "missing"


def test_expired_otp_is_rejected(app):
    user_id, challenge_id = _seed_otp(app, "042891", expired=True)

    with app.app_context():
        assert verify_otp_challenge(
            challenge_id,
            user_id,
            "generic",
            "042891",
        ) == "expired"


def test_cookie_replay_cannot_reset_otp_attempt_limit(app):
    user_id, challenge_id = _seed_otp(app, "042891")

    with app.app_context():
        outcomes = [
            verify_otp_challenge(
                challenge_id,
                user_id,
                "generic",
                "000000",
            )
            for _ in range(5)
        ]
        assert outcomes == ["invalid", "invalid", "invalid", "invalid", "locked"]
        assert verify_otp_challenge(
            challenge_id,
            user_id,
            "generic",
            "042891",
        ) == "missing"


def test_locked_challenge_cannot_be_reissued_inside_expiry_window(app):
    user_id, challenge_id = _seed_otp(app, "042891", attempts=5)

    with app.app_context():
        challenge = db.session.get(OtpChallenge, challenge_id)
        challenge.consumed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

        with pytest.raises(OtpChallengeRateLimited):
            issue_otp_challenge(user_id, "generic", code="112233")
