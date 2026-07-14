"""Exercise the populated 2025 schema upgrade against real MySQL."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
import sqlalchemy as sa


PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEGACY_MYSQL_STATEMENTS = (
    """CREATE TABLE `user` (
        id INTEGER PRIMARY KEY,
        has_voted BOOLEAN NOT NULL DEFAULT 0
    ) ENGINE=InnoDB""",
    """CREATE TABLE election (
        id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        status VARCHAR(20) NOT NULL,
        open_at DATETIME NULL,
        close_at DATETIME NULL,
        created_by INTEGER NULL,
        created_at DATETIME NULL
    ) ENGINE=InnoDB""",
    """CREATE TABLE regions (
        id INTEGER PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        CONSTRAINT uq_regions_name UNIQUE (name)
    ) ENGINE=InnoDB""",
    """CREATE TABLE electoral_roll (
        id INTEGER PRIMARY KEY,
        driver_license_number VARCHAR(255) NOT NULL,
        driver_license_hash VARCHAR(64) NOT NULL,
        full_name VARCHAR(255) NOT NULL,
        address_line1 VARCHAR(255) NOT NULL,
        address_line2 VARCHAR(255) NULL,
        suburb VARCHAR(255) NOT NULL,
        state VARCHAR(50) NOT NULL,
        postcode VARCHAR(50) NOT NULL,
        CONSTRAINT uq_roll_ciphertext UNIQUE (driver_license_number),
        CONSTRAINT uq_roll_hash UNIQUE (driver_license_hash)
    ) ENGINE=InnoDB""",
    """CREATE TABLE candidate (
        id INTEGER PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        party VARCHAR(120) NULL,
        position VARCHAR(120) NOT NULL,
        region_id INTEGER NOT NULL,
        created_at DATETIME NULL,
        CONSTRAINT fk_candidate_region FOREIGN KEY (region_id) REFERENCES regions(id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE vote (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NULL,
        candidate_id INTEGER NOT NULL,
        position VARCHAR(120) NOT NULL,
        vote_hash VARCHAR(64) NULL,
        created_at DATETIME NULL,
        CONSTRAINT uq_vote_user UNIQUE (user_id),
        CONSTRAINT fk_vote_user FOREIGN KEY (user_id) REFERENCES `user`(id),
        CONSTRAINT fk_vote_candidate FOREIGN KEY (candidate_id) REFERENCES candidate(id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB""",
    """CREATE TABLE vote_receipt (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        voted_at DATETIME NULL,
        CONSTRAINT uq_vote_receipt_user UNIQUE (user_id),
        CONSTRAINT fk_receipt_user FOREIGN KEY (user_id) REFERENCES `user`(id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB""",
    """CREATE TABLE blind_signature_token (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        ballot_nonce_hash VARCHAR(64) NOT NULL,
        issued_at DATETIME NULL,
        redeemed BOOLEAN NOT NULL DEFAULT 0,
        redeemed_at DATETIME NULL,
        CONSTRAINT uq_blind_sig_token_user UNIQUE (user_id),
        CONSTRAINT uq_blind_sig_token_nonce_hash UNIQUE (ballot_nonce_hash),
        CONSTRAINT fk_blind_token_user FOREIGN KEY (user_id) REFERENCES `user`(id)
            ON DELETE CASCADE
    ) ENGINE=InnoDB""",
    """CREATE TABLE alembic_version (
        version_num VARCHAR(64) NOT NULL PRIMARY KEY
    ) ENGINE=InnoDB""",
    "INSERT INTO alembic_version VALUES ('20251005_add_uq_vote_user')",
    "INSERT INTO `user` VALUES (1, 1)",
    "INSERT INTO election(id, name, status, created_at) VALUES (1, 'Legacy', 'closed', '2026-01-01 00:00:00')",
    "INSERT INTO regions VALUES (1, 'Melbourne')",
    """INSERT INTO electoral_roll VALUES (
        1, 'legacy-ciphertext', 'legacy-hash', 'Legacy Voter',
        '1 Legacy Street', NULL, 'Melbourne', 'VIC', '3000'
    )""",
    """INSERT INTO candidate VALUES (
        1, 'Candidate', 'Independent', 'Representative', 1,
        '2026-01-01 00:00:00'
    )""",
    """INSERT INTO vote VALUES (
        1, 1, 1, 'Representative', 'hash', '2026-01-02 00:00:00'
    )""",
    "INSERT INTO vote_receipt VALUES (1, 1, '2026-01-02 00:00:00')",
    """INSERT INTO blind_signature_token VALUES (
        1, 1,
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        NULL, 1, NULL
    )""",
)


def test_populated_legacy_schema_upgrades_on_real_mysql():
    if os.environ.get('MYSQL_LEGACY_MIGRATION_TEST') != '1':
        pytest.skip('requires the dedicated CI legacy-MySQL migration job')

    database_url = os.environ['DATABASE_URL']
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        existing = sa.inspect(connection).get_table_names()
        assert existing == []
        for statement in LEGACY_MYSQL_STATEMENTS:
            connection.execute(sa.text(statement))

    migrated = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app.wsgi:app', 'db', 'upgrade'],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr

    inspector = sa.inspect(engine)
    vote_columns = {column['name'] for column in inspector.get_columns('vote')}
    assert 'user_id' not in vote_columns
    assert {'voter_token', 'election_id'}.issubset(vote_columns)
    roll_columns = {
        column['name']: column
        for column in inspector.get_columns('electoral_roll')
    }
    assert roll_columns['full_name']['type'].length >= 1536

    with engine.connect() as connection:
        assert connection.execute(
            sa.text('SELECT election_id, candidate_id FROM vote WHERE id = 1')
        ).one() == (1, 1)
        assert connection.execute(
            sa.text('SELECT COUNT(*) FROM blind_signature_token')
        ).scalar_one() == 0
        assert connection.execute(
            sa.text('SELECT version_num FROM alembic_version')
        ).scalar_one() == '20260714_pii_envelope_v1'
