"""Authentication session, reset replay, and verified-email regressions."""

import time

import jwt
import pytest

from app import db
from app.models import BlindSignatureToken, Election, User
from app.routes.main import user_is_eligible_to_vote
from app.routes.password_reset import _get_serializer as reset_serializer
from app.routes.registration import _get_serializer as verification_serializer
from app.security.jwt_helpers import ALGORITHM, issue_token


def _set_non_test_delivery_environment(
    monkeypatch,
    base_url='https://vote.example.test',
):
    monkeypatch.setenv('PUBLIC_BASE_URL', base_url)
    monkeypatch.setenv('TRUSTED_HOSTS', 'vote.example.test')
    monkeypatch.setenv('ENABLE_MFA', 'true')
    monkeypatch.setenv('MAIL_SERVER', 'smtp.example.invalid')
    monkeypatch.setenv('MAIL_USERNAME', 'auth-test@example.invalid')
    monkeypatch.setenv('MAIL_PASSWORD', 'auth-test-mail-password')
    monkeypatch.setenv('MAIL_DEFAULT_SENDER', 'auth-test@example.invalid')


def _set_flask_login(client, user_id):
    with client.session_transaction() as flask_session:
        flask_session['_user_id'] = str(user_id)
        flask_session['_fresh'] = True


def test_non_test_request_rejects_flask_session_without_jwt(app):
    with app.app_context():
        user_id = User.query.filter_by(username='voter1').one().id
    client = app.test_client()
    _set_flask_login(client, user_id)
    with client.session_transaction() as flask_session:
        flask_session['mfa_pending_user_id'] = user_id
        flask_session['mfa_challenge_id'] = 'stale-challenge'

    app.config['TESTING'] = False
    try:
        response = client.get('/profile')
    finally:
        app.config['TESTING'] = True

    assert response.status_code == 302
    assert '/login' in response.headers['Location']
    assert any(
        header.startswith('otp_session=;')
        for header in response.headers.getlist('Set-Cookie')
    )
    with client.session_transaction() as flask_session:
        assert '_user_id' not in flask_session
        assert 'mfa_pending_user_id' not in flask_session
        assert 'mfa_challenge_id' not in flask_session


def test_non_test_request_preserves_anonymous_session_without_jwt(app):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session['anonymous_marker'] = 'keep'
        flask_session['_flashes'] = [('info', 'anonymous feedback')]

    app.config['TESTING'] = False
    try:
        response = client.get('/login-nonce')
    finally:
        app.config['TESTING'] = True

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session['anonymous_marker'] == 'keep'
        assert flask_session['_flashes'] == [('info', 'anonymous feedback')]


def test_non_test_request_preserves_pending_mfa_without_jwt(app):
    with app.app_context():
        user_id = User.query.filter_by(username='voter1').one().id
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session['mfa_pending_user_id'] = user_id
        flask_session['mfa_challenge_id'] = 'pending-challenge'

    app.config['TESTING'] = False
    try:
        response = client.get('/verify-mfa')
    finally:
        app.config['TESTING'] = True

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session['mfa_pending_user_id'] == user_id
        assert flask_session['mfa_challenge_id'] == 'pending-challenge'


def test_non_test_request_rejects_expired_jwt_and_clears_login(app):
    with app.app_context():
        user = User.query.filter_by(username='voter1').one()
        user_id = user.id
        now = int(time.time())
        expired = jwt.encode(
            {
                'sub': str(user.id),
                'iat': now - 120,
                'exp': now - 60,
                'ver': user.session_version,
            },
            app.config['SECRET_KEY'],
            algorithm=ALGORITHM,
        )

    client = app.test_client()
    _set_flask_login(client, user_id)
    client.set_cookie('session_token', expired)
    app.config['TESTING'] = False
    try:
        response = client.get('/profile')
    finally:
        app.config['TESTING'] = True

    assert response.status_code == 302
    assert '/login' in response.headers['Location']
    assert any(
        header.startswith('session_token=;')
        for header in response.headers.getlist('Set-Cookie')
    )


def test_password_reset_is_single_use_and_revokes_existing_jwt(app, client):
    with app.app_context():
        user = User.query.filter_by(username='voter1').one()
        user_id = user.id
        old_version = user.session_version
        old_token = issue_token(user.id, old_version)
        reset_token = reset_serializer().dumps(
            {'uid': user.id, 'ver': old_version}
        )

    first = client.post(
        f'/reset-password/{reset_token}',
        data={
            'new_password': 'FirstResetPassword123!',
            'confirm_password': 'FirstResetPassword123!',
        },
        follow_redirects=False,
    )
    assert first.status_code == 302

    replay = client.post(
        f'/reset-password/{reset_token}',
        data={
            'new_password': 'ReplayPassword456!',
            'confirm_password': 'ReplayPassword456!',
        },
        follow_redirects=True,
    )
    assert b'Invalid reset link' in replay.data

    with app.app_context():
        user = User.query.filter_by(username='voter1').one()
        assert user.session_version == old_version + 1
        assert user.check_password('FirstResetPassword123!')
        assert not user.check_password('ReplayPassword456!')

    authenticated = app.test_client()
    _set_flask_login(authenticated, user_id)
    authenticated.set_cookie('session_token', old_token)
    app.config['TESTING'] = False
    try:
        rejected = authenticated.get('/profile')
    finally:
        app.config['TESTING'] = True
    assert rejected.status_code == 302
    assert '/login' in rejected.headers['Location']
    assert any(
        header.startswith('otp_session=;')
        for header in rejected.headers.getlist('Set-Cookie')
    )


def test_matching_jwt_and_flask_session_authenticate_in_non_test_mode(app):
    with app.app_context():
        user = User.query.filter_by(username='voter1').one()
        user_id = user.id
        token = issue_token(user.id, user.session_version)

    client = app.test_client()
    _set_flask_login(client, user_id)
    client.set_cookie('session_token', token)
    app.config['TESTING'] = False
    try:
        response = client.get('/profile')
    finally:
        app.config['TESTING'] = True

    assert response.status_code == 200
    assert b'voter1' in response.data


@pytest.mark.parametrize(
    'next_target',
    [
        'https://attacker.example/phish',
        '//attacker.example/phish',
        'javascript:alert(1)',
    ],
)
def test_direct_login_rejects_external_next(client, next_target):
    response = client.post(
        '/login',
        query_string={'next': next_target},
        data={'username': 'voter1', 'password': 'Password@123!'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard')
    assert 'attacker.example' not in response.headers['Location']


def test_mfa_login_rejects_external_next(app, monkeypatch):
    import app as app_module
    import app.auth as auth_module

    monkeypatch.setattr(
        auth_module,
        'issue_otp_challenge',
        lambda user_id, purpose: ('challenge-id', '112233'),
    )
    monkeypatch.setattr(
        auth_module,
        'verify_otp_challenge',
        lambda challenge_id, user_id, purpose, code: 'valid',
    )
    monkeypatch.setattr(app_module.mail, 'send', lambda message: None)

    client = app.test_client()
    app.config['ENABLE_MFA'] = True
    try:
        password_step = client.post(
            '/login',
            query_string={'next': 'https://attacker.example/phish'},
            data={'username': 'voter1', 'password': 'Password@123!'},
            follow_redirects=False,
        )
        assert password_step.status_code == 302
        assert password_step.headers['Location'].endswith('/verify-mfa')
        with client.session_transaction() as flask_session:
            assert flask_session['mfa_pending_next'] == ''

        otp_step = client.post(
            '/verify-mfa',
            data={'otp': '112233'},
            follow_redirects=False,
        )
    finally:
        app.config['ENABLE_MFA'] = False

    assert otp_step.status_code == 302
    assert otp_step.headers['Location'].endswith('/dashboard')
    assert 'attacker.example' not in otp_step.headers['Location']


def test_registration_has_one_route_and_verification_gates_approval(app, client):
    register_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == '/register']
    assert [rule.endpoint for rule in register_rules] == ['auth.register']

    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        voter.email_verified = False
        voter.account_status = 'pending'
        voter.enrolment.status = 'pending'
        voter.enrolment.verified = False
        voter_id = voter.id
        verify_token = verification_serializer().dumps(voter.email)
        db.session.commit()

    client.post('/login', data={
        'username': 'admin',
        'password': 'Admin@123456!',
    })
    refused = client.post(
        f'/admin/users/approve/{voter_id}',
        follow_redirects=True,
    )
    assert b'must verify their email before approval' in refused.data
    with app.app_context():
        voter = db.session.get(User, voter_id)
        assert voter.account_status == 'pending'
        assert not voter.enrolment.verified

    verified = client.get(
        f'/verify-email/{verify_token}',
        follow_redirects=True,
    )
    assert b'Email verified successfully' in verified.data

    client.post(f'/admin/users/approve/{voter_id}')
    with app.app_context():
        voter = db.session.get(User, voter_id)
        assert voter.email_verified
        assert voter.account_status == 'approved'
        assert voter.enrolment.verified


def test_approved_unverified_voter_cannot_obtain_blind_authorization(app, client):
    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        voter.email_verified = False
        voter.account_status = 'approved'
        voter.enrolment.status = 'active'
        voter.enrolment.verified = True
        election = Election.query.filter_by(status='open').one()
        election_id = election.id
        voter_id = voter.id
        assert not user_is_eligible_to_vote(voter, election)
        db.session.commit()

    login = client.post(
        '/login',
        data={'username': 'voter1', 'password': 'Password@123!'},
    )
    assert login.status_code == 302
    response = client.post(
        '/vote/request-token',
        json={'election_id': election_id, 'blinded_ballot': '0x2'},
    )
    assert response.status_code == 403
    assert response.get_json() == {'error': 'Not eligible to vote'}
    with app.app_context():
        assert not BlindSignatureToken.query.filter_by(
            user_id=voter_id,
            election_id=election_id,
        ).first()


def test_admin_rejection_revokes_existing_session_epoch(app, client):
    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        voter_id = voter.id
        old_version = voter.session_version
        old_token = issue_token(voter.id, old_version)

    assert client.post(
        '/login',
        data={'username': 'admin', 'password': 'Admin@123456!'},
    ).status_code == 302
    assert client.post(f'/admin/users/reject/{voter_id}').status_code == 302

    with app.app_context():
        voter = db.session.get(User, voter_id)
        assert voter.account_status == 'rejected'
        assert voter.session_version == old_version + 1

    authenticated = app.test_client()
    _set_flask_login(authenticated, voter_id)
    authenticated.set_cookie('session_token', old_token)
    app.config['TESTING'] = False
    try:
        response = authenticated.get('/profile')
    finally:
        app.config['TESTING'] = True
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_password_commit_survives_replacement_token_failure(app, client, monkeypatch):
    assert client.post(
        '/login',
        data={'username': 'voter1', 'password': 'Password@123!'},
    ).status_code == 302

    def fail_token_issue(*_args, **_kwargs):
        raise RuntimeError('secret-leak-marker')

    monkeypatch.setattr(
        'app.security.jwt_helpers.issue_token',
        fail_token_issue,
    )
    response = client.post(
        '/change-password',
        data={
            'current_password': 'Password@123!',
            'new_password': 'CommittedPassword456!',
            'confirm_password': 'CommittedPassword456!',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Password changed successfully. Please sign in again.' in response.data
    assert b'secret-leak-marker' not in response.data
    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        assert voter.check_password('CommittedPassword456!')


def test_password_edge_whitespace_round_trips_across_auth_flows(app):
    original_password = ' OriginalWhitespacePassword123! '
    changed_password = ' ChangedWhitespacePassword456! '
    reset_password = ' ResetWhitespacePassword789! '

    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        voter.set_password(original_password)
        db.session.commit()

    client = app.test_client()
    login = client.post(
        '/login',
        data={'username': 'voter1', 'password': original_password},
        follow_redirects=False,
    )
    assert login.status_code == 302

    changed = client.post(
        '/change-password',
        data={
            'current_password': original_password,
            'new_password': changed_password,
            'confirm_password': changed_password,
        },
        follow_redirects=False,
    )
    assert changed.status_code == 302

    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        assert voter.check_password(changed_password)
        assert not voter.check_password(changed_password.strip())
        reset_token = reset_serializer().dumps(
            {'uid': voter.id, 'ver': voter.session_version}
        )

    reset_client = app.test_client()
    reset = reset_client.post(
        f'/reset-password/{reset_token}',
        data={
            'new_password': reset_password,
            'confirm_password': reset_password,
        },
        follow_redirects=False,
    )
    assert reset.status_code == 302

    with app.app_context():
        voter = User.query.filter_by(username='voter1').one()
        assert voter.check_password(reset_password)
        assert not voter.check_password(reset_password.strip())


def test_cookie_secure_defaults_fail_safe(monkeypatch):
    monkeypatch.delenv('DEPLOYMENT_ENV', raising=False)
    monkeypatch.delenv('FLASK_ENV', raising=False)
    monkeypatch.delenv('SESSION_COOKIE_SECURE', raising=False)
    monkeypatch.setenv('SECRET_KEY', 'cookie-test-secret-key-at-least-32-bytes')
    monkeypatch.setenv(
        'VOTER_PII_KEY_BASE64',
        'SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg=',
    )
    monkeypatch.setenv(
        'LICENSE_HASH_PEPPER',
        'cookie-test-license-pepper-at-least-32-bytes',
    )
    monkeypatch.setenv(
        'AUDIT_HMAC_KEY',
        'cookie-test-audit-hmac-key-at-least-32-bytes',
    )
    _set_non_test_delivery_environment(monkeypatch)

    from app import create_app

    secure_app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert secure_app.config['SESSION_COOKIE_SECURE'] is True


def test_local_demo_defaults_to_http_compatible_cookie(monkeypatch):
    monkeypatch.setenv('DEPLOYMENT_ENV', 'local-demo')
    monkeypatch.delenv('FLASK_ENV', raising=False)
    monkeypatch.delenv('SESSION_COOKIE_SECURE', raising=False)
    monkeypatch.setenv('SECRET_KEY', 'local-test-secret-key-at-least-32-bytes')
    monkeypatch.setenv(
        'VOTER_PII_KEY_BASE64',
        'SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg=',
    )
    monkeypatch.setenv(
        'LICENSE_HASH_PEPPER',
        'local-test-license-pepper-at-least-32-bytes',
    )
    monkeypatch.setenv(
        'AUDIT_HMAC_KEY',
        'local-test-audit-hmac-key-at-least-32-bytes',
    )
    _set_non_test_delivery_environment(monkeypatch)

    from app import create_app

    local_app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert local_app.config['SESSION_COOKIE_SECURE'] is False


def test_production_rejects_insecure_cookie_override(monkeypatch):
    monkeypatch.setenv('DEPLOYMENT_ENV', 'production')
    monkeypatch.delenv('FLASK_ENV', raising=False)
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'false')

    from app import create_app

    with pytest.raises(RuntimeError, match='Production requires'):
        create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
