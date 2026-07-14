"""CSRF enforcement for authenticated JSON endpoints."""

import pytest
from flask import request, session
from werkzeug.exceptions import Forbidden

from app.security.csrf import _validate_csrf


def _enable_csrf(app):
    app.config["TESTING"] = False
    app.config["WTF_CSRF_ENABLED"] = True


def test_authenticated_json_request_requires_csrf_header(app):
    _enable_csrf(app)
    with app.test_request_context(
        "/vote/request-token",
        method="POST",
        json={"blinded_ballot": "2", "election_id": 1},
    ):
        assert request.endpoint == "main.request_blind_token"
        session["_csrf_token"] = "expected-token"
        with pytest.raises(Forbidden):
            _validate_csrf()


def test_authenticated_json_request_accepts_matching_csrf_header(app):
    _enable_csrf(app)
    with app.test_request_context(
        "/vote/request-token",
        method="POST",
        json={"blinded_ballot": "2", "election_id": 1},
        headers={"X-CSRF-Token": "expected-token"},
    ):
        session["_csrf_token"] = "expected-token"
        assert _validate_csrf() is None


def test_explicit_anonymous_ballot_endpoint_remains_csrf_exempt(app):
    _enable_csrf(app)
    with app.test_request_context(
        "/vote/cast",
        method="POST",
        json={"ballot": "00", "signature": "01"},
    ):
        assert request.endpoint == "main.cast_anonymous_ballot"
        _validate_csrf()
