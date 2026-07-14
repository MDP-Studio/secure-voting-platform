"""Canonical email-link, trusted-host, and resend recovery regressions."""

from app import db, mail
from app.models import User
from app.routes.password_reset import _send_reset_email
from app.routes.registration import send_verification_email


def test_security_email_links_ignore_the_request_host(app):
    app.config['PUBLIC_BASE_URL'] = 'https://vote.example.test'
    with app.app_context():
        user = User.query.filter_by(username='voter1').one()
        with app.test_request_context('/register', base_url='http://attacker.test'):
            with mail.record_messages() as outbox:
                assert send_verification_email(user)
                assert _send_reset_email(user)

    assert len(outbox) == 2
    for message in outbox:
        assert 'https://vote.example.test/' in message.body
        assert 'attacker.test' not in message.body


def test_untrusted_forwarded_host_is_rejected(app, client):
    app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1']
    response = client.get(
        '/login',
        headers={'X-Forwarded-Host': 'attacker.example'},
    )
    assert response.status_code == 400


def test_resend_is_enumeration_neutral_and_only_targets_pending_unverified(
    app,
    client,
):
    generic_message = (
        b'If a pending unverified account exists for that address, a new '
        b'verification link has been sent.'
    )
    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        voter.email_verified = False
        voter.account_status = 'pending'
        voter_email = voter.email
        db.session.commit()

    with mail.record_messages() as pending_outbox:
        pending_response = client.post(
            '/resend-verification',
            data={'email': voter_email},
            follow_redirects=True,
        )
    assert pending_response.status_code == 200
    assert generic_message in pending_response.data
    assert len(pending_outbox) == 1

    with mail.record_messages() as missing_outbox:
        missing_response = client.post(
            '/resend-verification',
            data={'email': 'missing@example.invalid'},
            follow_redirects=True,
        )
    assert missing_response.status_code == 200
    assert generic_message in missing_response.data
    assert missing_outbox == []

    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        voter.account_status = 'approved'
        db.session.commit()
    with mail.record_messages() as approved_outbox:
        approved_response = client.post(
            '/resend-verification',
            data={'email': voter_email},
            follow_redirects=True,
        )
    assert approved_response.status_code == 200
    assert generic_message in approved_response.data
    assert approved_outbox == []
