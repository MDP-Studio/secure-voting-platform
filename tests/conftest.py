import pytest
import os
import tempfile
from app import create_app, db
from app.models import User, Candidate, Vote


@pytest.fixture
def app():
    """Create and configure a test app instance."""
    # Create a temporary database for testing
    db_fd, db_path = tempfile.mkstemp()

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SECRET_KEY': 'test-secret-key',
        'WTF_CSRF_ENABLED': False,  # Disable CSRF for testing
    })

    with app.app_context():
        db.create_all()
        # Create test data
        _create_test_data()

    yield app

    # Cleanup - try multiple times on Windows
    import time
    for _ in range(5):
        try:
            os.close(db_fd)
            os.unlink(db_path)
            break
        except OSError:
            time.sleep(0.1)  # Wait a bit and try again


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()


def _create_test_data():
    """Create test data for smoke tests."""
    # Create test user
    test_user = User(username='testuser', email='test@example.com')
    test_user.set_password('testpass')
    db.session.add(test_user)

    # Create admin user
    admin_user = User(username='admin', email='admin@example.com', is_admin=True)
    admin_user.set_password('adminpass')
    db.session.add(admin_user)

    # Create test candidates
    candidate1 = Candidate(name='Alice Johnson', position='Mayor')
    candidate2 = Candidate(name='Bob Smith', position='Mayor')
    db.session.add_all([candidate1, candidate2])

    db.session.commit()