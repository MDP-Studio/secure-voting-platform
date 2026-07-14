"""Regression tests for request-aware database credential routing."""

from flask import g
from sqlalchemy import event

from app import RoutingSession, db
from app.utils.db_utils import _build_db_binds


def test_runtime_session_uses_request_aware_session_class(app):
    with app.test_request_context("/"):
        session = db.session()
        assert isinstance(session, RoutingSession)


def test_active_request_bind_selects_the_named_engine(app):
    with app.test_request_context("/"):
        session = db.session()

        g._active_bind = "voters"
        assert session.get_bind() is db.engines["voters"]

        g._active_bind = "admin"
        assert session.get_bind() is db.engines["admin"]


def test_authenticated_roles_select_expected_request_bind(client, app):
    app.config["DEBUG_DB_BIND"] = True
    manager_login = client.post(
        "/login",
        data={"username": "admin", "password": "Admin@123456!"},
    )
    assert manager_login.status_code == 302
    manager_page = client.get("/dashboard")
    assert manager_page.headers["X-DB-Bind"] == "admin"

    client.get("/logout")
    voter_login = client.post(
        "/login",
        data={"username": "voter1", "password": "Password@123!"},
    )
    assert voter_login.status_code == 302
    voter_page = client.get("/dashboard")
    assert voter_page.headers["X-DB-Bind"] == "voters"


def test_anonymous_cast_ignores_attached_identity_without_logging_user_out(client, app):
    app.config["DEBUG_DB_BIND"] = True

    for username, password, expected_dashboard_bind in (
        ("admin", "Admin@123456!", "admin"),
        ("voter1", "Password@123!", "voters"),
    ):
        login = client.post(
            "/login",
            data={"username": username, "password": password},
        )
        assert login.status_code == 302

        cast = client.post("/vote/cast", json=[])
        assert cast.status_code == 400
        assert cast.headers["X-DB-Bind"] == "voters"

        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.headers["X-DB-Bind"] == expected_dashboard_bind
        client.get("/logout")


def test_authenticated_requests_never_execute_on_primary_engine(client, app):
    """Identity lookup and request queries must stay off migration credentials."""
    primary_statements = []

    def record_primary_statement(*_args):
        primary_statements.append(True)

    with app.app_context():
        primary_engine = db.engine
        event.listen(
            primary_engine,
            "before_cursor_execute",
            record_primary_statement,
        )

    try:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "Admin@123456!"},
        )
        assert login.status_code == 302
        primary_statements.clear()

        response = client.get("/dashboard")

        assert response.status_code == 200
        assert primary_statements == []
    finally:
        event.remove(
            primary_engine,
            "before_cursor_execute",
            record_primary_statement,
        )


def test_bind_urls_use_configured_database_and_escape_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://base:base-password-2026@db:3306/customdb",
    )
    monkeypatch.setenv("VOTING_ADMIN_USER", "admin_user")
    monkeypatch.setenv("VOTING_ADMIN_PASS", "admin:a@pass-2026")
    monkeypatch.setenv("VOTING_VOTER_USER", "voter_user")
    monkeypatch.setenv("VOTING_VOTER_PASS", "voter:v@pass-2026")
    monkeypatch.delenv("MYSQL_DATABASE", raising=False)

    binds = _build_db_binds("unused")

    assert binds["admin"] == (
        "mysql+pymysql://admin_user:admin%3Aa%40pass-2026@db:3306/customdb"
    )
    assert binds["voters"] == (
        "mysql+pymysql://voter_user:voter%3Av%40pass-2026@db:3306/customdb"
    )


def test_non_sqlite_bind_configuration_requires_all_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://base:base-password-2026@db:3306/votingdb",
    )
    for name in (
        "VOTING_ADMIN_USER",
        "VOTING_ADMIN_PASS",
        "VOTING_VOTER_USER",
        "VOTING_VOTER_PASS",
    ):
        monkeypatch.delenv(name, raising=False)

    import pytest

    with pytest.raises(RuntimeError, match="Missing split-database credentials"):
        _build_db_binds("unused")


def test_non_sqlite_bind_configuration_rejects_placeholder_passwords(monkeypatch):
    import pytest

    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://base:base-password-2026@db:3306/votingdb",
    )
    monkeypatch.setenv("VOTING_ADMIN_USER", "admin_user")
    monkeypatch.setenv("VOTING_ADMIN_PASS", "CHANGE_ME_PASSWORD")
    monkeypatch.setenv("VOTING_VOTER_USER", "voter_user")
    monkeypatch.setenv("VOTING_VOTER_PASS", "voter-password-2026")

    with pytest.raises(RuntimeError, match="VOTING_ADMIN_PASS"):
        _build_db_binds("unused")
