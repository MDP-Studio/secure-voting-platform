import ast
import json
import logging
from pathlib import Path

from flask import Flask

from app.logging_service import (
    AUDIT_HANDLER_NAME,
    AUDIT_LOGGER_NAME,
    init_audit_logging,
    record_audit_event,
    verify_audit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_EVENTS = {
    "app/routes/admin_users.py": {
        "approve_user": "user.approve",
        "reject_user": "user.reject",
    },
    "app/routes/elections.py": {
        "create_election": "election.create",
        "open_election": "election.open",
        "close_election": "election.close",
    },
    "app/routes/candidates.py": {
        "create_candidate": "candidate.create",
        "update_candidate": "candidate.update",
        "delete_candidate": "candidate.delete",
    },
    "app/routes/main.py": {
        "request_blind_token": "ballot_authorization.issue",
        "cast_anonymous_ballot": "ballot.cast",
    },
    "app/routes/results.py": {
        "sign_election_results": "result.sign",
    },
}


def _is_db_commit(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "session"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "db"
    )


def _is_audit_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "record_audit_event"
    )


def _audit_call_for(function, expected_action):
    matches = []
    for node in ast.walk(function):
        if not _is_audit_call(node):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        action = keywords.get("action")
        if isinstance(action, ast.Constant) and action.value == expected_action:
            matches.append((node, keywords))
    assert len(matches) == 1, (
        f"{function.name} must emit exactly one {expected_action!r} audit event"
    )
    return matches[0]


def test_required_mutations_emit_once_after_successful_commit():
    """Keep the high-risk mutation inventory complete and post-commit."""
    for relative_path, expected_functions in REQUIRED_EVENTS.items():
        source_path = PROJECT_ROOT / relative_path
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=relative_path)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for function_name, expected_action in expected_functions.items():
            function = functions[function_name]
            audit_call, _ = _audit_call_for(function, expected_action)
            commit_lines = [
                node.lineno for node in ast.walk(function) if _is_db_commit(node)
            ]
            assert commit_lines, f"{relative_path}:{function_name} has no commit"
            assert max(commit_lines) < audit_call.lineno, (
                f"{relative_path}:{function_name} must audit only after commit succeeds"
            )


def test_blind_ballot_events_do_not_add_cross_phase_identifiers():
    """Authorization identifies the voter; casting remains election-only."""
    source_path = PROJECT_ROOT / "app/routes/main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    authorization_call, authorization = _audit_call_for(
        functions["request_blind_token"],
        "ballot_authorization.issue",
    )
    cast_call, cast = _audit_call_for(
        functions["cast_anonymous_ballot"],
        "ballot.cast",
    )

    expected_fields = {"actor_id", "action", "target_type", "target_id"}
    assert set(authorization) == expected_fields
    assert set(cast) == expected_fields
    assert ast.unparse(authorization["actor_id"]) == "locked_user.id"
    assert ast.unparse(authorization["target_id"]) == "active_election.id"
    assert isinstance(cast["actor_id"], ast.Constant)
    assert cast["actor_id"].value is None
    assert ast.unparse(cast["target_id"]) == "election.id"
    assert authorization_call.lineno < cast_call.lineno


def test_structured_audit_chain_excludes_operational_request_logs(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_key = "audit-test-key-with-at-least-32-bytes"
    app = Flask("audit-completeness-test")
    app.config.update(
        TESTING=True,
        AUDIT_LOG_PATH=str(audit_path),
        AUDIT_HMAC_KEY=audit_key,
    )

    root_logger = logging.getLogger("")
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    previous_audit_level = audit_logger.level
    previous_audit_propagate = audit_logger.propagate
    previous_app_propagate = app.logger.propagate

    try:
        init_audit_logging(app)
        record_audit_event(
            actor_id=42,
            action="election.close",
            target_type="election",
            target_id=7,
        )
        app.logger.warning("single application warning")

        entries = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert len(entries) == 1
        assert sum(entry["message"] == "security_action" for entry in entries) == 1
        assert all(entry["message"] != "single application warning" for entry in entries)
        assert entries[0]["extra"] == {
            "actor": {"id": "42"},
            "action": "election.close",
            "target": {"type": "election", "id": "7"},
            "outcome": "success",
        }

        chain_ok, errors = verify_audit(audit_path, audit_key.encode("utf-8"))
        assert chain_ok, errors

        entries[0]["extra"]["outcome"] = "tampered"
        audit_path.write_text(
            "\n".join(json.dumps(entry) for entry in entries) + "\n",
            encoding="utf-8",
        )
        chain_ok, errors = verify_audit(audit_path, audit_key.encode("utf-8"))
        assert not chain_ok
        assert any("hmac mismatch" in error for error in errors)
    finally:
        for logger in (root_logger, app.logger, audit_logger):
            for handler in list(logger.handlers):
                if getattr(handler, "name", None) == AUDIT_HANDLER_NAME:
                    logger.removeHandler(handler)
                    handler.close()
        audit_logger.setLevel(previous_audit_level)
        audit_logger.propagate = previous_audit_propagate
        app.logger.propagate = previous_app_propagate
