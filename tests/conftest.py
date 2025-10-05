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
    # Create admin user (matching init_db.py)
    admin = User(username='admin', email='admin@voting.com', is_admin=True)
    admin.set_password('admin123')
    db.session.add(admin)
    
    # Create sample voter (matching init_db.py)
    voter1 = User(username='voter1', email='voter1@email.com', is_admin=False)
    voter1.set_password('password123')
    db.session.add(voter1)
    
    # Create sample candidates (matching init_db.py)
    candidates = [
        Candidate(name='John Smith', party='Labor Party', position='House of Representatives', constituency='Sydney'),
        Candidate(name='Sarah Johnson', party='Liberal Party', position='House of Representatives', constituency='Sydney'),
        Candidate(name='Mike Brown', party='Greens', position='House of Representatives', constituency='Sydney'),
    ]
    db.session.add_all(candidates)
    
    db.session.commit()