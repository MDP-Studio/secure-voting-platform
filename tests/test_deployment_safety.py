"""Fail-closed deployment and one-shot bootstrap regressions."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import create_app
from app.init_db import init_database
from app.security.vault_client import VaultClient
from scripts.bootstrap_manager import _required
from scripts.init_db_users import _required_env as _required_db_env
from scripts.vault_integration_check import _read_token


def test_non_test_app_requires_explicit_secret_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv(
        "VOTER_PII_KEY_BASE64",
        "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg=",
    )
    monkeypatch.setenv(
        "LICENSE_HASH_PEPPER",
        "deployment-test-license-pepper-at-least-32-bytes",
    )
    monkeypatch.setenv(
        "AUDIT_HMAC_KEY",
        "deployment-test-audit-hmac-key-at-least-32-bytes",
    )

    with pytest.raises(RuntimeError, match="SECRET_KEY must be an explicit"):
        create_app(
            {
                "TESTING": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'app.db'}",
            }
        )


def test_non_test_app_requires_stable_pii_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("SECRET_KEY", "deployment-test-secret-key-at-least-32-bytes")
    monkeypatch.setenv(
        "LICENSE_HASH_PEPPER",
        "deployment-test-license-pepper-at-least-32-bytes",
    )
    monkeypatch.setenv(
        "AUDIT_HMAC_KEY",
        "deployment-test-audit-hmac-key-at-least-32-bytes",
    )
    monkeypatch.delenv("VOTER_PII_KEY_BASE64", raising=False)

    with pytest.raises(RuntimeError, match="VOTER_PII_KEY_BASE64 is required"):
        create_app({"TESTING": False})


@pytest.mark.parametrize(
    ("secret_name", "invalid_value"),
    (
        ("SECRET_KEY", "short"),
        ("LICENSE_HASH_PEPPER", "CHANGE_ME_LICENSE_PEPPER"),
        ("AUDIT_HMAC_KEY", "REPLACE_AUDIT_HMAC_KEY"),
    ),
)
def test_non_test_app_rejects_weak_or_placeholder_secrets(
    monkeypatch,
    tmp_path,
    secret_name,
    invalid_value,
):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("SECRET_KEY", "deployment-test-secret-key-at-least-32-bytes")
    monkeypatch.setenv(
        "VOTER_PII_KEY_BASE64",
        "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg=",
    )
    monkeypatch.setenv(
        "LICENSE_HASH_PEPPER",
        "deployment-test-license-pepper-at-least-32-bytes",
    )
    monkeypatch.setenv(
        "AUDIT_HMAC_KEY",
        "deployment-test-audit-hmac-key-at-least-32-bytes",
    )
    monkeypatch.setenv(secret_name, invalid_value)

    with pytest.raises(RuntimeError, match=secret_name):
        create_app({"TESTING": False})


def test_demo_seed_requires_explicit_opt_in(app, monkeypatch):
    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)

    with pytest.raises(RuntimeError, match="Demo seeding is disabled"):
        init_database(app)


def test_vault_check_reads_scoped_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "vault-token"
    token_file.write_text("scoped-test-token\n", encoding="utf-8")
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("VAULT_TOKEN_FILE", str(token_file))

    assert _read_token() == "scoped-test-token"


def test_vault_check_rejects_ambiguous_token_sources(monkeypatch, tmp_path):
    token_file = tmp_path / "vault-token"
    token_file.write_text("scoped-test-token", encoding="utf-8")
    monkeypatch.setenv("VAULT_TOKEN", "environment-token")
    monkeypatch.setenv("VAULT_TOKEN_FILE", str(token_file))

    with pytest.raises(RuntimeError, match="only one"):
        _read_token()

    assert VaultClient().is_enabled is False


def test_manager_bootstrap_rejects_placeholder_secret(monkeypatch):
    monkeypatch.setenv(
        "BOOTSTRAP_MANAGER_PASSWORD",
        "CHANGE_ME_USE_A_UNIQUE_STRONG_PASSWORD",
    )

    with pytest.raises(RuntimeError, match="non-placeholder"):
        _required("BOOTSTRAP_MANAGER_PASSWORD")


def test_database_bootstrap_rejects_placeholder_secret(monkeypatch):
    monkeypatch.setenv("MYSQL_ROOT_PASSWORD", "CHANGE_ME_ROOT_PASSWORD")

    with pytest.raises(RuntimeError, match="MYSQL_ROOT_PASSWORD"):
        _required_db_env("MYSQL_ROOT_PASSWORD", secret=True)


def test_one_time_manager_bootstrap_creates_no_demo_accounts(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = tmp_path / "bootstrap.db"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "DEPLOYMENT_ENV": "development",
            "SECRET_KEY": "bootstrap-test-only-secret-key-32-bytes",
            "VOTER_PII_KEY_BASE64": (
                "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg="
            ),
            "LICENSE_HASH_PEPPER": (
                "bootstrap-test-only-license-pepper-at-least-32-bytes"
            ),
            "AUDIT_HMAC_KEY": (
                "bootstrap-test-only-audit-hmac-key-at-least-32-bytes"
            ),
            "PUBLIC_BASE_URL": "http://localhost",
            "TRUSTED_HOSTS": "localhost,127.0.0.1",
            "MAIL_SERVER": "smtp.example.invalid",
            "MAIL_USERNAME": "bootstrap@example.invalid",
            "MAIL_PASSWORD": "bootstrap-test-mail-password",
            "MAIL_DEFAULT_SENDER": "bootstrap@example.invalid",
            "BOOTSTRAP_MANAGER_USERNAME": "initial_manager",
            "BOOTSTRAP_MANAGER_EMAIL": "manager@example.invalid",
            "BOOTSTRAP_MANAGER_PASSWORD": "BootstrapOnly@12345",
            "BOOTSTRAP_MANAGER_LICENSE": "BOOTSTRAP01",
            "BOOTSTRAP_MANAGER_LICENSE_STATE": "VIC",
            "ALLOW_DEMO_SEED": "false",
            "CREATE_TEST_VOTERS": "false",
        }
    )

    commands = (
        [sys.executable, "-m", "flask", "db", "upgrade"],
        [sys.executable, "scripts/bootstrap_reference_data.py"],
        [sys.executable, "scripts/bootstrap_manager.py"],
        [sys.executable, "scripts/bootstrap_manager.py"],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    with sqlite3.connect(database) as connection:
        users = connection.execute(
            'SELECT username, account_status, email_verified FROM "user"'
        ).fetchall()
        assert users == [("initial_manager", "approved", 1)]
        assert connection.execute(
            'SELECT COUNT(*) FROM "user" WHERE username LIKE "testvoter%"'
        ).fetchone() == (0,)
