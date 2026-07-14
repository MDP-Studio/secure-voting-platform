"""Live MySQL authentication and least-privilege regression checks."""

import os

import pymysql
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("MYSQL_PERMISSION_TEST") != "1",
    reason="requires the CI MySQL permission fixture",
)


def _connect(username, password):
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=username,
        password=password,
        database=os.environ["MYSQL_DATABASE"],
        autocommit=False,
    )


def _assert_allowed(connection, statement):
    with connection.cursor() as cursor:
        cursor.execute(statement)
    connection.rollback()


def _assert_denied(connection, statement):
    with pytest.raises(pymysql.MySQLError) as captured:
        with connection.cursor() as cursor:
            cursor.execute(statement)
    connection.rollback()
    assert captured.value.args[0] in {1142, 1143}


def test_voter_account_can_persist_voting_state_but_not_manage_rosters():
    connection = _connect(
        os.environ["VOTING_VOTER_USER"],
        os.environ["VOTING_VOTER_PASS"],
    )
    try:
        _assert_allowed(
            connection,
            "SELECT id FROM election WHERE id = -1 FOR SHARE",
        )
        _assert_denied(
            connection,
            "SELECT id FROM election WHERE id = -1 FOR UPDATE",
        )
        _assert_allowed(
            connection,
            "INSERT INTO vote (voter_token, candidate_id, election_id, position) "
            "SELECT 'permission-probe', 1, 1, 'probe' WHERE FALSE",
        )
        _assert_allowed(
            connection,
            "INSERT INTO blind_signature_token (user_id, election_id) "
            "SELECT 1, 1 WHERE FALSE",
        )
        _assert_allowed(
            connection,
            "INSERT INTO spent_ballot_nullifier "
            "(election_id, nullifier_hash, spent_at) "
            "SELECT 1, REPEAT('a', 64), NOW() WHERE FALSE",
        )
        _assert_denied(
            connection,
            "UPDATE election SET blind_signing_key_id = blind_signing_key_id "
            "WHERE id = -1",
        )
        _assert_denied(
            connection,
            "UPDATE electoral_roll SET status = status WHERE id = -1",
        )
        _assert_denied(
            connection,
            "UPDATE blind_signature_token SET election_id = election_id "
            "WHERE id = -1",
        )
        _assert_denied(
            connection,
            "UPDATE candidate SET name = name WHERE id = -1",
        )
        _assert_denied(
            connection,
            "INSERT INTO signed_election_result "
            "(election_id, payload, signature, signer_backend, "
            "signature_algorithm, signing_key_id, signed_at) "
            "SELECT 1, '{}', 'x', 'local-rsa', 'rsa-pss-sha256', "
            "REPEAT('a', 64), NOW() WHERE FALSE",
        )
        with connection.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            grants = "\n".join(row[0] for row in cursor.fetchall())
        assert "ALL PRIVILEGES" not in grants
    finally:
        connection.close()


def test_admin_account_can_manage_elections_but_cannot_write_ballots():
    connection = _connect(
        os.environ["VOTING_ADMIN_USER"],
        os.environ["VOTING_ADMIN_PASS"],
    )
    try:
        _assert_allowed(
            connection,
            "UPDATE election SET status = status WHERE id = -1",
        )
        _assert_allowed(
            connection,
            "UPDATE candidate SET name = name WHERE id = -1",
        )
        _assert_denied(
            connection,
            "INSERT INTO vote (voter_token, candidate_id, election_id, position) "
            "SELECT 'admin-probe', 1, 1, 'probe' WHERE FALSE",
        )
        with connection.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            grants = "\n".join(row[0] for row in cursor.fetchall())
        assert "ALL PRIVILEGES" not in grants
    finally:
        connection.close()
