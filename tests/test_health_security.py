"""Public health probes expose state, not internal diagnostics."""

from app import db


def test_readiness_does_not_expose_runtime_mode(client):
    response = client.get('/health/ready')
    assert response.status_code == 200
    assert response.get_json() == {
        'status': 'ready',
        'database': 'connected',
    }


def test_readiness_failure_is_generic(client, monkeypatch):
    def fail_probe(*_args, **_kwargs):
        raise RuntimeError('private-database-diagnostic')

    monkeypatch.setattr(db.session, 'execute', fail_probe)
    response = client.get('/health/ready')
    assert response.status_code == 503
    assert response.get_json() == {
        'status': 'not ready',
        'database': 'disconnected',
    }
    assert b'private-database-diagnostic' not in response.data
