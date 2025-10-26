import pytest
import os
import tempfile
from datetime import date
from app import create_app, db
from app.models import User, Candidate, Vote, Role, Region, ElectoralRoll


def pytest_addoption(parser):
    parser.addoption("--base-url", action="store", default="http://localhost", help="Base URL for integration tests")


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
        'ENABLE_MFA': False,  # Disable MFA for testing
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
    # Create roles
    voter_role = Role(name='voter', description='Regular voter')
    delegate_role = Role(name='delegate', description='Delegate user')
    manager_role = Role(name='manager', description='Manager/admin user')
    db.session.add_all([voter_role, delegate_role, manager_role])
    db.session.commit()
    
    # Create sample region
    default_region = Region(name='Sydney')
    db.session.add(default_region)
    db.session.commit()
    
    # Create admin user (matching init_db.py)
    admin = User(
        username='admin', 
        email='admin@voting.com',
        driver_lic_no='ADMIN001',
        driver_lic_state='NSW',
        account_status='approved'
    )
    admin.role_id = manager_role.id
    admin.set_password('AdminSecurePass123!')
    db.session.add(admin)
    
    # Create sample voter (matching init_db.py)
    voter1 = User(
        username='voter1', 
        email='voter1@email.com',
        driver_lic_no='DL001',
        driver_lic_state='NSW',
        account_status='approved'
    )
    voter1.role_id = voter_role.id
    voter1.set_password('VoterSecurePass123!')
    db.session.add(voter1)
    db.session.commit()  # Commit to get user.id
    
    # Create enrolment for voter1
    enrolment = ElectoralRoll(
        roll_number='TEST001',
        driver_license_number='DL123456',
        full_name='Test Voter',
        date_of_birth=date(1990, 1, 1),
        address_line1='123 Test St',
        suburb='Test Suburb',
        state='NSW',
        postcode='2000',
        region=default_region,
        status='active',
        verified=True,
        user=voter1
    )
    db.session.add(enrolment)
    
    # Create sample candidates (matching init_db.py)
    candidates = [
        Candidate(name='John Smith', party='Labor Party', position='House of Representatives', region=default_region),
        Candidate(name='Sarah Johnson', party='Liberal Party', position='House of Representatives', region=default_region),
        Candidate(name='Mike Brown', party='Greens', position='House of Representatives', region=default_region),
    ]
    db.session.add_all(candidates)
    
    db.session.commit()