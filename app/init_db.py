# init_db.py
import os
from datetime import datetime, date
from app import db
from app.models import User, Role, Region, Candidate, ElectoralRoll

# Import test voter data (optional)
try:
    from app.generate_test_voters import get_test_voters
    TEST_VOTERS_AVAILABLE = True
except ImportError:
    TEST_VOTERS_AVAILABLE = False
    print("⚠️  Test voter generator not available")


# small helper so we don't duplicate rows
def get_or_create(model, defaults=None, **kwargs):
    obj = model.query.filter_by(**kwargs).first()
    if obj:
        return obj, False
    params = {**(defaults or {}), **kwargs}
    obj = model(**params)
    db.session.add(obj)
    return obj, True


def init_database(app):
    with app.app_context():
        try:
            # 1) create tables
            db.create_all()
        except Exception as e:
            print(f"❌ Failed to create database tables: {e}")
            print("💡 This might be due to a database schema mismatch.")
            print("   If you're running in Docker with a persistent database,")
            print("   you may need to reset the database or run migrations.")
            print("   For development: delete the database volume/file and restart.")
            raise

        try:
            # 2) seed roles
            for name, desc in [
                ("voter", "Can cast one vote"),
                ("delegate", "Manages candidates, cannot vote"),
                ("manager", "System admin, cannot vote"),
            ]:
                get_or_create(Role, description=desc, name=name)

            # 3) seed regions
            for rname in ["Sydney", "VIC east", "VIC west", "NSW", "SA"]:
                get_or_create(Region, name=rname)

            db.session.flush()  # ensure IDs exist for FKs
        except Exception as e:
            print(f"❌ Failed to seed roles and regions: {e}")
            db.session.rollback()
            raise

        try:
            # quick lookups
            voter_role = Role.query.filter_by(name="voter").first()
            delegate_role = Role.query.filter_by(name="delegate").first()
            manager_role = Role.query.filter_by(name="manager").first()
            sydney = Region.query.filter_by(name="Sydney").first()

            # 4) users (NOTE: __tablename__ for User should be "user")
            if not User.query.filter_by(username="admin").first():
                admin = User(
                    username="admin",
                    email="secsoftsysa3@myyahoo.com",
                    role=manager_role,
                    has_voted=False,
                    created_at=datetime.utcnow(),
                )
                admin.set_password("admin123")
                db.session.add(admin)
            else:
                admin = User.query.filter_by(username="admin").first()
                admin.email = "secsoftsysa3@myyahoo.com"

            if not User.query.filter_by(username="delegate1").first():
                delegate1 = User(
                    username="delegate1",
                    email="delegate1@voting.com",
                    role=delegate_role,
                    has_voted=False,
                    created_at=datetime.utcnow(),
                )
                delegate1.set_password("delegate123")
                db.session.add(delegate1)

            if not User.query.filter_by(username="voter1").first():
                voter1 = User(
                    username="voter1",
                    email="voter1@voting.com",
                    role=voter_role,
                    has_voted=False,
                    created_at=datetime.utcnow(),
                )
                voter1.set_password("password123")
                db.session.add(voter1)

            if not User.query.filter_by(username='lix').first():
                lix = User(
                    username='lix',
                    email='2508027683@qq.com',
                    role=voter_role,
                    has_voted=False,
                    created_at=datetime.utcnow(),
                )
                lix.set_password('password123')
                db.session.add(lix)
        
            # add your own user here

            # Create test voters if enabled via environment variable
            create_test_voters = os.environ.get('CREATE_TEST_VOTERS', 'false').lower() == 'true'
            if create_test_voters and TEST_VOTERS_AVAILABLE:
                print("🧪 Creating 100 test voters for testing purposes...")
                test_voters_data = get_test_voters()
                created_count = 0
                
                for voter_data in test_voters_data:
                    # Check if test voter already exists
                    if not User.query.filter_by(username=voter_data['username']).first():
                        test_user = User(
                            username=voter_data['username'],
                            email=voter_data['email'],
                            role=voter_role,
                            has_voted=False,
                            created_at=datetime.utcnow(),
                        )
                        test_user.set_password(voter_data['password'])
                        db.session.add(test_user)
                        created_count += 1
                
                if created_count > 0:
                    print(f"✅ Created {created_count} test voters")
                else:
                    print("ℹ️  Test voters already exist, skipping creation")
            elif create_test_voters and not TEST_VOTERS_AVAILABLE:
                print("⚠️  CREATE_TEST_VOTERS is enabled but test voter generator is not available")

            db.session.flush()
            voter1 = User.query.filter_by(username="voter1").first()  # refresh to ensure id
        except Exception as e:
            print(f"❌ Failed to create users: {e}")
            print("💡 This might indicate a schema mismatch in the User or Role tables.")
            db.session.rollback()
            raise

        try:
            # 5) electoral roll entry for voter1 (active & verified in Sydney)
            if voter1 and not ElectoralRoll.query.filter_by(user_id=voter1.id).first():
                er = ElectoralRoll(
                    roll_number="ER-0001",
                    driver_license_number="DL12345678",
                    full_name="Voter One",
                    date_of_birth=date(1990, 5, 10),
                    address_line1="1 King St",
                    suburb="Sydney",
                    state="NSW",
                    postcode="2000",
                    region_id=sydney.id,
                    status="active",
                    verified=True,
                    verified_at=datetime.utcnow(),
                    user_id=voter1.id,
                )
                db.session.add(er)

            # Create electoral roll entries for test voters if they were created
            if create_test_voters and TEST_VOTERS_AVAILABLE:
                print("🗳️  Creating electoral roll entries for test voters...")
                test_voters_data = get_test_voters()
                regions = Region.query.all()  # Get all available regions
                roll_entries_created = 0
                
                for voter_data in test_voters_data:
                    # Find the corresponding user
                    test_user = User.query.filter_by(username=voter_data['username']).first()
                    if test_user and not ElectoralRoll.query.filter_by(user_id=test_user.id).first():
                        # Assign random region for testing
                        random_region = regions[hash(voter_data['username']) % len(regions)]
                        
                        er = ElectoralRoll(
                            roll_number=voter_data['roll_number'],
                            driver_license_number=voter_data['driver_license_number'],
                            full_name=voter_data['full_name'],
                            date_of_birth=voter_data['date_of_birth'],
                            address_line1=voter_data['address_line1'],
                            suburb=voter_data['suburb'],
                            state=voter_data['state'],
                            postcode=voter_data['postcode'],
                            region_id=random_region.id,
                            status="active",
                            verified=True,
                            verified_at=datetime.utcnow(),
                            user_id=test_user.id,
                        )
                        db.session.add(er)
                        roll_entries_created += 1
                
                if roll_entries_created > 0:
                    print(f"✅ Created {roll_entries_created} electoral roll entries for test voters")
                else:
                    print("ℹ️  Electoral roll entries for test voters already exist")

        except Exception as e:
            print(f"❌ Failed to create electoral roll entry: {e}")
            print("💡 This might indicate a schema mismatch in the ElectoralRoll table.")
            db.session.rollback()
            raise

        try:
            # 6) candidates (use region_id, not constituency)
            if Candidate.query.count() == 0:
                db.session.add_all(
                    [
                        Candidate(
                            name="John Smith",
                            party="Labor Party",
                            position="House of Representatives",
                            region_id=sydney.id,
                        ),
                        Candidate(
                            name="Sarah Johnson",
                            party="Liberal Party",
                            position="House of Representatives",
                            region_id=sydney.id,
                        ),
                        Candidate(
                            name="Mike Brown",
                            party="Greens",
                            position="House of Representatives",
                            region_id=sydney.id,
                        ),
                    ]
                )
        except Exception as e:
            print(f"❌ Failed to create candidates: {e}")
            print("💡 This might indicate a schema mismatch in the Candidate table.")
            print("   Common issue: missing 'region_id' column added in recent model changes.")
            print("   Solution: Reset your database or run schema migrations.")
            db.session.rollback()
            raise

        try:
            db.session.commit()
        except Exception as e:
            print(f"❌ Failed to commit database changes: {e}")
            db.session.rollback()
            raise

        print(" 🧀✅ Database initialized")
        print(" 🧑‍💻 Logins you can use:")
        print("  manager  → admin / admin123")
        print("  delegate → delegate1 / delegate123")
        print("  voter    → voter1 / password123")


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    init_database(app)
