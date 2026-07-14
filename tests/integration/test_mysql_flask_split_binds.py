"""Real-MySQL request-routing coverage for production split credentials."""

import json
import os
import secrets

from sqlalchemy import text

from app.security.blind_signature import hash_ballot


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
    ),
    "Referer": "http://localhost/login",
}


def _login(client, username, password):
    nonce_response = client.get("/login-nonce", headers=BROWSER_HEADERS)
    assert nonce_response.status_code == 200
    nonce = nonce_response.get_json()["nonce"]

    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "login_nonce": nonce,
        },
        headers=BROWSER_HEADERS,
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response


def _normalized(statements):
    return [statement.lower().replace("`", "") for statement in statements]


def test_real_mysql_requests_use_only_the_expected_runtime_binds(mysql_split_app):
    target = mysql_split_app
    app = target["app"]
    engines = target["engines"]
    statements = target["statements"]

    assert app.config["TESTING"] is False
    assert engines["default"].url.username not in {
        os.environ["VOTING_VOTER_USER"],
        os.environ["VOTING_ADMIN_USER"],
    }
    assert engines["voters"].url.username == os.environ["VOTING_VOTER_USER"]
    assert engines["admin"].url.username == os.environ["VOTING_ADMIN_USER"]

    voter_client = app.test_client()
    voter_login = _login(
        voter_client,
        target["voter_username"],
        target["voter_password"],
    )
    assert voter_login.headers["X-DB-Bind"] == "voters"

    key_response = voter_client.get(
        f"/vote/blind-key?election_id={target['open_election_id']}",
        headers=BROWSER_HEADERS,
    )
    assert key_response.status_code == 200
    public_key = key_response.get_json()
    modulus = int(public_key["n"], 16)
    exponent = int(public_key["e"], 16)

    ballot = json.dumps(
        {
            "candidate_id": target["open_candidate_id"],
            "election_id": target["open_election_id"],
            "nonce": secrets.token_hex(32),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    message = hash_ballot(ballot, modulus)
    blinding_factor = secrets.randbelow(modulus - 3) + 2
    blinded = (message * pow(blinding_factor, exponent, modulus)) % modulus

    authorization_response = voter_client.post(
        "/vote/request-token",
        json={
            "blinded_ballot": hex(blinded),
            "election_id": target["open_election_id"],
        },
        headers=BROWSER_HEADERS,
    )
    assert authorization_response.status_code == 200
    assert authorization_response.headers["X-DB-Bind"] == "voters"
    blind_signature = int(
        authorization_response.get_json()["blind_signature"],
        16,
    )
    signature = (
        blind_signature * pow(blinding_factor, -1, modulus)
    ) % modulus

    # A voter cookie must not become identity at the anonymous cast boundary.
    malformed_cookie_cast = voter_client.post(
        "/vote/cast",
        json=[],
        headers=BROWSER_HEADERS,
    )
    assert malformed_cookie_cast.status_code == 400
    assert malformed_cookie_cast.headers["X-DB-Bind"] == "voters"

    # A manager cookie must also be ignored. The successful ballot insert is
    # decisive on MySQL because the admin credential intentionally lacks the
    # voter-only ballot INSERT grant.
    manager_client = app.test_client()
    manager_login = _login(
        manager_client,
        target["manager_username"],
        target["manager_password"],
    )
    assert manager_login.headers["X-DB-Bind"] == "voters"
    cast_response = manager_client.post(
        "/vote/cast",
        json={"ballot": ballot.hex(), "signature": hex(signature)},
        headers=BROWSER_HEADERS,
    )
    assert cast_response.status_code == 200
    assert cast_response.headers["X-DB-Bind"] == "voters"

    with engines["voters"].connect() as connection:
        vote_count = connection.execute(
            text("SELECT COUNT(*) FROM vote WHERE election_id = :election_id"),
            {"election_id": target["open_election_id"]},
        ).scalar_one()
        authorization_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM blind_signature_token "
                "WHERE election_id = :election_id AND user_id = :user_id"
            ),
            {
                "election_id": target["open_election_id"],
                "user_id": target["voter_id"],
            },
        ).scalar_one()
        spent_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM spent_ballot_nullifier "
                "WHERE election_id = :election_id"
            ),
            {"election_id": target["open_election_id"]},
        ).scalar_one()
    assert vote_count == 1
    assert authorization_count == 1
    assert spent_count == 1

    updated_name = "CI Draft Candidate Updated"
    roster_response = manager_client.post(
        f"/candidates/{target['draft_candidate_id']}/update",
        data={"name": updated_name},
        headers=BROWSER_HEADERS,
        follow_redirects=False,
    )
    assert roster_response.status_code == 302
    assert roster_response.headers["X-DB-Bind"] == "admin"

    with engines["admin"].connect() as connection:
        persisted_name = connection.execute(
            text("SELECT name FROM candidate WHERE id = :candidate_id"),
            {"candidate_id": target["draft_candidate_id"]},
        ).scalar_one()
    assert persisted_name == updated_name

    voter_sql = _normalized(statements["voters"])
    admin_sql = _normalized(statements["admin"])
    assert any("update user " in statement for statement in voter_sql)
    assert any("insert into vote " in statement for statement in voter_sql)
    assert any("insert into blind_signature_token " in statement for statement in voter_sql)
    assert any("insert into spent_ballot_nullifier " in statement for statement in voter_sql)
    assert not any("insert into vote_receipt " in statement for statement in voter_sql)
    assert any("update candidate " in statement for statement in admin_sql)
    assert statements["default"] == []
