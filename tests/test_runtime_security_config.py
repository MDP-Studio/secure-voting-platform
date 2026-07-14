"""Fail-closed hosted configuration and developer-surface regressions."""

from pathlib import Path

import pytest

from app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_INDICATORS = (
    'HEROKU_APP_NAME',
    'AWS_REGION',
    'GOOGLE_CLOUD_PROJECT',
    'AZURE_SUBSCRIPTION_ID',
)


def _set_valid_runtime(monkeypatch, tmp_path, *, deployment='development', flask=''):
    for name in PRODUCTION_INDICATORS:
        monkeypatch.delenv(name, raising=False)
    if deployment is None:
        monkeypatch.delenv('DEPLOYMENT_ENV', raising=False)
    else:
        monkeypatch.setenv('DEPLOYMENT_ENV', deployment)
    if flask is None:
        monkeypatch.delenv('FLASK_ENV', raising=False)
    else:
        monkeypatch.setenv('FLASK_ENV', flask)

    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'runtime.db'}")
    monkeypatch.setenv('SECRET_KEY', 'runtime-test-secret-key-at-least-32-bytes')
    monkeypatch.setenv(
        'VOTER_PII_KEY_BASE64',
        'SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg=',
    )
    monkeypatch.setenv(
        'LICENSE_HASH_PEPPER',
        'runtime-test-license-pepper-at-least-32-bytes',
    )
    monkeypatch.setenv(
        'AUDIT_HMAC_KEY',
        'runtime-test-audit-hmac-key-at-least-32-bytes',
    )
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://vote.example.test')
    monkeypatch.setenv('TRUSTED_HOSTS', 'vote.example.test')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'true')
    monkeypatch.setenv('ENABLE_MFA', 'true')
    monkeypatch.setenv('MAIL_SERVER', 'smtp.example.invalid')
    monkeypatch.setenv('MAIL_PORT', '587')
    monkeypatch.setenv('MAIL_USE_TLS', 'true')
    monkeypatch.setenv('MAIL_USE_SSL', 'false')
    monkeypatch.setenv('MAIL_USERNAME', 'runtime@example.invalid')
    monkeypatch.setenv('MAIL_PASSWORD', 'runtime-test-mail-password')
    monkeypatch.setenv('MAIL_DEFAULT_SENDER', 'runtime@example.invalid')


@pytest.mark.parametrize(
    ('deployment', 'flask', 'hosted_indicator'),
    (
        (' production ', '', None),
        ('staging', '', None),
        (None, ' production ', None),
        (None, None, 'AWS_REGION'),
    ),
)
def test_every_production_like_signal_rejects_insecure_cookies(
    monkeypatch,
    tmp_path,
    deployment,
    flask,
    hosted_indicator,
):
    _set_valid_runtime(
        monkeypatch,
        tmp_path,
        deployment=deployment,
        flask=flask,
    )
    if hosted_indicator:
        monkeypatch.setenv(hosted_indicator, 'ap-southeast-2')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'false')

    with pytest.raises(RuntimeError, match='Production requires SESSION_COOKIE_SECURE'):
        create_app()


def test_no_environment_or_hosted_indicator_still_defaults_fail_closed(
    monkeypatch,
    tmp_path,
):
    _set_valid_runtime(
        monkeypatch,
        tmp_path,
        deployment=None,
        flask=None,
    )
    monkeypatch.delenv('DATABASE_URL')
    for name in PRODUCTION_INDICATORS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'false')

    with pytest.raises(RuntimeError, match='Production requires SESSION_COOKIE_SECURE'):
        create_app()


def test_production_rejects_http_public_origin(monkeypatch, tmp_path):
    _set_valid_runtime(monkeypatch, tmp_path, deployment='production')
    monkeypatch.setenv('PUBLIC_BASE_URL', 'http://vote.example.test')

    with pytest.raises(RuntimeError, match='HTTPS PUBLIC_BASE_URL'):
        create_app()


def test_production_rejects_mfa_off(monkeypatch, tmp_path):
    _set_valid_runtime(monkeypatch, tmp_path, deployment='production')
    monkeypatch.setenv('ENABLE_MFA', 'false')

    with pytest.raises(RuntimeError, match='ENABLE_MFA=true'):
        create_app()


def test_production_rejects_plain_smtp(monkeypatch, tmp_path):
    _set_valid_runtime(monkeypatch, tmp_path, deployment='production')
    monkeypatch.setenv('MAIL_USE_TLS', 'false')
    monkeypatch.setenv('MAIL_USE_SSL', 'false')

    with pytest.raises(RuntimeError, match='SMTP requires TLS or SSL'):
        create_app()


def test_non_test_runtime_requires_mail_delivery(monkeypatch, tmp_path):
    _set_valid_runtime(monkeypatch, tmp_path)
    monkeypatch.delenv('MAIL_PASSWORD')

    with pytest.raises(RuntimeError, match='MAIL_PASSWORD is required'):
        create_app()


def test_public_hostname_must_be_trusted(monkeypatch, tmp_path):
    _set_valid_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv('TRUSTED_HOSTS', 'different.example.test')

    with pytest.raises(RuntimeError, match='must include the hostname'):
        create_app()


@pytest.mark.parametrize(
    ('deployment', 'flask'),
    (
        ('production', 'development'),
        ('development', 'production'),
    ),
)
def test_conflicting_environment_signals_are_rejected(
    monkeypatch,
    tmp_path,
    deployment,
    flask,
):
    _set_valid_runtime(
        monkeypatch,
        tmp_path,
        deployment=deployment,
        flask=flask,
    )

    with pytest.raises(RuntimeError, match='conflicting security modes'):
        create_app()


def test_unknown_environment_is_rejected(monkeypatch, tmp_path):
    _set_valid_runtime(monkeypatch, tmp_path, deployment='preview')

    with pytest.raises(RuntimeError, match='Unsupported DEPLOYMENT_ENV'):
        create_app()


@pytest.mark.parametrize('deployment', ('production', 'staging'))
def test_developer_routes_are_absent_in_hosted_modes(
    monkeypatch,
    tmp_path,
    deployment,
):
    _set_valid_runtime(monkeypatch, tmp_path, deployment=deployment)
    app = create_app()

    response = app.test_client().get(
        '/dev/dashboard',
        base_url='https://vote.example.test',
    )
    assert response.status_code == 404
    assert not any(rule.rule.startswith('/dev/') for rule in app.url_map.iter_rules())


def test_compose_wires_security_email_origin_and_maintenance_runner():
    compose = (PROJECT_ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
    for name in (
        'PUBLIC_BASE_URL',
        'TRUSTED_HOSTS',
        'ENABLE_MFA',
        'MAIL_SERVER',
        'MAIL_PORT',
        'MAIL_USE_TLS',
        'MAIL_USE_SSL',
        'MAIL_USERNAME',
        'MAIL_PASSWORD',
        'MAIL_DEFAULT_SENDER',
    ):
        assert f'{name}:' in compose
    assert 'migration-runner:' in compose
    assert 'profiles: ["maintenance"]' in compose

    waf_config = (PROJECT_ROOT / 'nginx/conf.d/waf.conf').read_text(
        encoding='utf-8'
    )
    assert 'X-Forwarded-Host $server_name' not in waf_config
    assert waf_config.count('X-Forwarded-Host $host') >= 5
