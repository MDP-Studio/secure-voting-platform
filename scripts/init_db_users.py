#!/usr/bin/env python3
"""Provision environment-driven, least-privilege MySQL application accounts."""

import os
import re
import time

import pymysql


IDENTIFIER = re.compile(r"\A[A-Za-z0-9_]+\Z")

ADMIN_TABLE_PRIVILEGES = {
    "user": "UPDATE",
    "electoral_roll": "UPDATE",
    "candidate": "INSERT, UPDATE, DELETE",
    "election": "INSERT, UPDATE",
    "result_signing_public_key": "INSERT",
    "signed_election_result": "INSERT",
}

# SELECT is granted database-wide and is sufficient for the FOR SHARE locking
# reads used by voter flows. Exclusive FOR UPDATE locks stay on admin paths or
# voter-owned rows where the credential already has UPDATE permission.
# Writes are limited to state a voter or anonymous registration flow actually
# owns. In particular, this credential cannot alter election state, the
# election signing-key anchor, enrolment decisions, or issued authorizations.
VOTER_TABLE_PRIVILEGES = {
    "user": "INSERT, UPDATE",
    "electoral_roll": "INSERT",
    "vote": "INSERT",
    "vote_receipt": "INSERT",
    "blind_signature_token": "INSERT",
    "spent_ballot_nullifier": "INSERT",
    "otp_challenge": "INSERT, UPDATE, DELETE",
}


def _required_env(name, *, secret=False):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    if secret and (
        len(value) < 16
        or value.upper().startswith(("CHANGE_ME", "REPLACE_"))
    ):
        raise RuntimeError(
            f"{name} must be an explicit non-placeholder value of at least 16 characters"
        )
    return value


def _identifier(value, label):
    if not IDENTIFIER.fullmatch(value):
        raise RuntimeError(f"{label} must contain only letters, digits, or underscore")
    return value


def _connection_settings():
    return {
        "host": os.environ.get("DB_HOST", "db"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": "root",
        "password": _required_env("MYSQL_ROOT_PASSWORD", secret=True),
        "database": "mysql",
        "autocommit": False,
    }


def wait_for_db(max_attempts=30, delay=2):
    """Wait for MySQL to accept authenticated root connections."""
    print("Waiting for the database to be ready...")
    settings = _connection_settings()
    for attempt in range(1, max_attempts + 1):
        try:
            connection = pymysql.connect(**settings)
            connection.close()
            print("Database is ready.")
            return
        except pymysql.MySQLError as exc:
            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Database not ready after {max_attempts} attempts"
                ) from exc
            print(
                f"Database not ready ({attempt}/{max_attempts}); "
                f"retrying in {delay} seconds."
            )
            time.sleep(delay)


def _reset_account(cursor, username, password):
    cursor.execute(
        "CREATE USER IF NOT EXISTS %s@'%%' "
        "IDENTIFIED WITH caching_sha2_password BY %s",
        (username, password),
    )
    # Synchronize password rotation on every controlled startup.
    cursor.execute(
        "ALTER USER %s@'%%' IDENTIFIED WITH caching_sha2_password BY %s",
        (username, password),
    )
    cursor.execute(
        "REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@'%%'",
        (username,),
    )


def _grant_database_select(cursor, database, username):
    cursor.execute(
        f"GRANT SELECT ON `{database}`.* TO %s@'%%'",
        (username,),
    )


def _grant_table_privileges(cursor, database, username, grants):
    for table, privileges in grants.items():
        _identifier(table, "table name")
        cursor.execute(
            f"GRANT {privileges} ON `{database}`.`{table}` TO %s@'%%'",
            (username,),
        )


def create_db_users():
    """Create or rotate both accounts and replace every prior grant."""
    _required_env("MYSQL_PASSWORD", secret=True)
    database = _identifier(_required_env("MYSQL_DATABASE"), "MYSQL_DATABASE")
    admin_user = _identifier(
        _required_env("VOTING_ADMIN_USER"),
        "VOTING_ADMIN_USER",
    )
    voter_user = _identifier(
        _required_env("VOTING_VOTER_USER"),
        "VOTING_VOTER_USER",
    )
    if admin_user == voter_user:
        raise RuntimeError("Admin and voter database usernames must differ")
    admin_password = _required_env("VOTING_ADMIN_PASS", secret=True)
    voter_password = _required_env("VOTING_VOTER_PASS", secret=True)

    connection = pymysql.connect(**_connection_settings())
    try:
        with connection.cursor() as cursor:
            _reset_account(cursor, admin_user, admin_password)
            _reset_account(cursor, voter_user, voter_password)

            _grant_database_select(cursor, database, admin_user)
            _grant_table_privileges(
                cursor,
                database,
                admin_user,
                ADMIN_TABLE_PRIVILEGES,
            )
            _grant_database_select(cursor, database, voter_user)
            _grant_table_privileges(
                cursor,
                database,
                voter_user,
                VOTER_TABLE_PRIVILEGES,
            )
        connection.commit()
        print("Database application users provisioned successfully.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    wait_for_db()
    create_db_users()
