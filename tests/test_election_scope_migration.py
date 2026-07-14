"""Regression test for the legacy-to-election-scoped database migration."""

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


LEGACY_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE user (
    id INTEGER PRIMARY KEY,
    has_voted BOOLEAN NOT NULL DEFAULT 0
);
CREATE TABLE election (
    id INTEGER PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL,
    open_at DATETIME,
    close_at DATETIME,
    created_by INTEGER,
    created_at DATETIME
);
CREATE TABLE regions (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);
CREATE TABLE electoral_roll (
    id INTEGER PRIMARY KEY,
    driver_license_number VARCHAR(255) NOT NULL,
    driver_license_hash VARCHAR(64) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    address_line1 VARCHAR(255) NOT NULL,
    address_line2 VARCHAR(255),
    suburb VARCHAR(255) NOT NULL,
    state VARCHAR(50) NOT NULL,
    postcode VARCHAR(50) NOT NULL,
    CONSTRAINT uq_roll_ciphertext UNIQUE(driver_license_number)
);
CREATE TABLE candidate (
    id INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    party VARCHAR(120),
    position VARCHAR(120) NOT NULL,
    region_id INTEGER NOT NULL REFERENCES regions(id),
    created_at DATETIME
);
CREATE TABLE vote (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES user(id),
    candidate_id INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    position VARCHAR(120) NOT NULL,
    vote_hash VARCHAR(64),
    created_at DATETIME,
    CONSTRAINT uq_vote_user UNIQUE(user_id)
);
CREATE TABLE vote_receipt (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    voted_at DATETIME,
    CONSTRAINT uq_vote_receipt_user UNIQUE(user_id)
);
CREATE TABLE blind_signature_token (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    ballot_nonce_hash VARCHAR(64) NOT NULL UNIQUE,
    issued_at DATETIME,
    redeemed BOOLEAN NOT NULL DEFAULT 0,
    redeemed_at DATETIME,
    CONSTRAINT uq_blind_sig_token_user UNIQUE(user_id)
);
CREATE TABLE alembic_version (
    version_num VARCHAR(64) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version VALUES ('20251005_add_uq_vote_user');
INSERT INTO user VALUES (1, 1);
INSERT INTO election(id, name, status, created_at)
VALUES (1, 'Legacy', 'closed', '2026-01-01 00:00:00');
INSERT INTO regions VALUES (1, 'Sydney');
INSERT INTO electoral_roll VALUES (
    1,
    'legacy-ciphertext',
    'legacy-hash',
    'Legacy Voter',
    '1 Legacy Street',
    NULL,
    'Legacy Suburb',
    'NSW',
    '2000'
);
INSERT INTO candidate
VALUES (1, 'Candidate', 'Independent', 'Representative', 1, '2026-01-01 00:00:00');
INSERT INTO vote
VALUES (
    1,
    1,
    1,
    'Representative',
    'hash',
    '2026-01-02 00:00:00'
);
INSERT INTO vote_receipt VALUES (1, 1, '2026-01-02 00:00:00');
INSERT INTO blind_signature_token
VALUES (
    1,
    1,
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    NULL,
    1,
    NULL
);
"""


def test_election_scope_migration_preserves_legacy_ballots(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(LEGACY_SCHEMA)

    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "DEPLOYMENT_ENV": "development",
            "SECRET_KEY": "migration-test-only-secret-key-32-bytes-minimum",
            "VOTER_PII_KEY_BASE64": (
                "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg="
            ),
            "LICENSE_HASH_PEPPER": (
                "migration-test-license-pepper-at-least-32-bytes"
            ),
            "AUDIT_HMAC_KEY": (
                "migration-test-audit-hmac-key-at-least-32-bytes"
            ),
            "PUBLIC_BASE_URL": "http://localhost",
            "MAIL_SERVER": "localhost",
            "MAIL_USERNAME": "migration-test-user",
            "MAIL_PASSWORD": "migration-test-password",
            "MAIL_DEFAULT_SENDER": "migration@example.test",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT election_id FROM candidate"
        ).fetchone() == (1,)
        assert connection.execute("SELECT election_id FROM vote").fetchone() == (1,)
        vote_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(vote)")
        }
        assert "user_id" not in vote_columns
        assert "voter_token" in vote_columns
        voter_token = connection.execute("SELECT voter_token FROM vote").fetchone()[0]
        assert len(voter_token) == 64
        user_columns = {
            row[1] for row in connection.execute('PRAGMA table_info("user")')
        }
        assert "has_voted" not in user_columns
        assert connection.execute(
            "SELECT election_id FROM vote_receipt"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM blind_signature_token"
        ).fetchone() == (0,)
        token_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(blind_signature_token)"
            )
        }
        assert token_columns == {"id", "user_id", "election_id"}
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260714_pii_envelope_v1",)
        pii_column_types = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(electoral_roll)")
        }
        assert pii_column_types["driver_license_number"].upper() == "VARCHAR(255)"
        for field in ("full_name", "address_line1", "address_line2", "suburb"):
            assert pii_column_types[field].upper() == "VARCHAR(1536)"
        assert pii_column_types["state"].upper() == "VARCHAR(512)"
        assert pii_column_types["postcode"].upper() == "VARCHAR(512)"
        assert connection.execute(
            "SELECT driver_license_number, driver_license_hash, state, postcode "
            "FROM electoral_roll WHERE id = 1"
        ).fetchone() == ("legacy-ciphertext", "legacy-hash", "NSW", "2000")
        unique_index_columns = {
            tuple(
                column[2]
                for column in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                )
            )
            for index in connection.execute("PRAGMA index_list(electoral_roll)")
            if index[2]
        }
        assert ("driver_license_number",) not in unique_index_columns
        assert ("driver_license_hash",) in unique_index_columns
        election_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'election'"
        ).fetchone()[0]
        assert "status IN ('draft', 'open', 'closed')" in election_schema
        election_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(election)")
        }
        assert "blind_signing_key_id" in election_columns
        assert "blind_key_recovery_required" in election_columns
        assert "session_version" in user_columns
        assert connection.execute(
            "SELECT blind_key_recovery_required FROM election WHERE id = 1"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'signed_election_result'"
        ).fetchone() == ("signed_election_result",)
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'result_signing_public_key'"
        ).fetchone() == ("result_signing_public_key",)
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'spent_ballot_nullifier'"
        ).fetchone() == ("spent_ballot_nullifier",)
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'otp_challenge'"
        ).fetchone() == ("otp_challenge",)
        result_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(signed_election_result)"
            )
        }
        assert {
            "signer_backend",
            "signature_algorithm",
            "signing_key_id",
            "signing_key_version",
        }.issubset(result_columns)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_fresh_database_upgrade_creates_current_schema(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = tmp_path / "fresh.db"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "DEPLOYMENT_ENV": "development",
            "SECRET_KEY": "migration-test-only-secret-key-32-bytes-minimum",
            "VOTER_PII_KEY_BASE64": (
                "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg="
            ),
            "LICENSE_HASH_PEPPER": (
                "migration-test-license-pepper-at-least-32-bytes"
            ),
            "AUDIT_HMAC_KEY": (
                "migration-test-audit-hmac-key-at-least-32-bytes"
            ),
            "PUBLIC_BASE_URL": "http://localhost",
            "MAIL_SERVER": "localhost",
            "MAIL_USERNAME": "migration-test-user",
            "MAIL_PASSWORD": "migration-test-password",
            "MAIL_DEFAULT_SENDER": "migration@example.test",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "election",
            "candidate",
            "vote",
            "vote_receipt",
            "blind_signature_token",
            "spent_ballot_nullifier",
            "result_signing_public_key",
            "signed_election_result",
            "otp_challenge",
        }.issubset(tables)
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260714_pii_envelope_v1",)
        pii_column_types = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(electoral_roll)")
        }
        assert pii_column_types["driver_license_number"].upper() == "VARCHAR(255)"
        for field in ("full_name", "address_line1", "address_line2", "suburb"):
            assert pii_column_types[field].upper() == "VARCHAR(1536)"
        assert pii_column_types["state"].upper() == "VARCHAR(512)"
        assert pii_column_types["postcode"].upper() == "VARCHAR(512)"
        unique_index_columns = {
            tuple(
                column[2]
                for column in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                )
            )
            for index in connection.execute("PRAGMA index_list(electoral_roll)")
            if index[2]
        }
        assert ("driver_license_number",) not in unique_index_columns
        assert ("driver_license_hash",) in unique_index_columns
        user_columns = {
            row[1] for row in connection.execute('PRAGMA table_info("user")')
        }
        assert "session_version" in user_columns
        vote_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(vote)")
        }
        assert "election_id" in vote_columns
        assert "user_id" not in vote_columns
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_open_legacy_authorization_history_is_quarantined(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = tmp_path / "ambiguous-open-legacy.db"
    legacy_schema = LEGACY_SCHEMA.replace(
        "VALUES (1, 'Legacy', 'closed'",
        "VALUES (1, 'Legacy', 'open'",
        1,
    ).replace(
        "    NULL,\n    1,\n    NULL\n);",
        "    NULL,\n    0,\n    NULL\n);",
        1,
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(legacy_schema)

    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "DEPLOYMENT_ENV": "development",
            "SECRET_KEY": "migration-test-only-secret-key-32-bytes-minimum",
            "VOTER_PII_KEY_BASE64": (
                "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg="
            ),
            "LICENSE_HASH_PEPPER": (
                "migration-test-license-pepper-at-least-32-bytes"
            ),
            "AUDIT_HMAC_KEY": (
                "migration-test-audit-hmac-key-at-least-32-bytes"
            ),
            "PUBLIC_BASE_URL": "http://localhost",
            "MAIL_SERVER": "localhost",
            "MAIL_USERNAME": "migration-test-user",
            "MAIL_PASSWORD": "migration-test-password",
            "MAIL_DEFAULT_SENDER": "migration@example.test",
        }
    )
    migrated = subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status, blind_signing_key_id, "
            "blind_key_recovery_required FROM election WHERE id = 1"
        ).fetchone() == ("open", None, 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM blind_signature_token"
        ).fetchone() == (0,)

    reconciled = subprocess.run(
        [sys.executable, "scripts/anchor_open_election_keys.py"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert reconciled.returncode != 0
    assert "Manual recovery is required" in (
        reconciled.stdout + reconciled.stderr
    )

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT blind_signing_key_id FROM election WHERE id = 1"
        ).fetchone() == (None,)


def test_partial_current_schema_is_refused_instead_of_stamped(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = tmp_path / "partial-current.db"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "DEPLOYMENT_ENV": "development",
            "SECRET_KEY": "migration-test-only-secret-key-32-bytes-minimum",
            "VOTER_PII_KEY_BASE64": (
                "SdJcGfF7m2Kly1lpi/53LOineNBCJz9FFiJWM4GNUDg="
            ),
            "LICENSE_HASH_PEPPER": (
                "migration-test-license-pepper-at-least-32-bytes"
            ),
            "AUDIT_HMAC_KEY": (
                "migration-test-audit-hmac-key-at-least-32-bytes"
            ),
            "PUBLIC_BASE_URL": "http://localhost",
            "TRUSTED_HOSTS": "localhost,127.0.0.1",
            "MAIL_SERVER": "smtp.example.invalid",
            "MAIL_USERNAME": "migration@example.invalid",
            "MAIL_PASSWORD": "migration-test-mail-password",
            "MAIL_DEFAULT_SENDER": "migration@example.invalid",
        }
    )
    initial = subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE spent_ballot_nullifier")
        connection.execute(
            "UPDATE alembic_version SET version_num = ?",
            ("20251005_add_uq_vote_user",),
        )

    resumed = subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resumed.returncode != 0
    assert "Refusing to stamp a partial election-integrity schema" in (
        resumed.stdout + resumed.stderr
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20251005_add_uq_vote_user",)


def test_election_scope_downgrade_is_fail_closed():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260714_election_scope.py"
    )
    spec = importlib.util.spec_from_file_location(
        "election_scope_migration_under_test",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(RuntimeError, match="Refusing to downgrade election scoping"):
        module.downgrade()
