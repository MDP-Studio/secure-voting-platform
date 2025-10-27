# init_db.py
import os
from datetime import datetime, date, timezone
from app import db
from app.models import (
    User,
    Role,
    Region,
    Candidate,
    ElectoralRoll,
)
from werkzeug.security import generate_password_hash
from app.utils.db_utils import wait_for_db

# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------

# Import test voter data (optional)
try:
    from app.generate_test_voters import get_test_voters
    TEST_VOTERS_AVAILABLE = True
except ImportError:
    TEST_VOTERS_AVAILABLE = False
    print("⚠️  Test voter generator not available")


# small helper so we don't duplicate rows
def get_or_create(model, defaults=None, **kwargs):
    """
    Simple get-or-create helper to avoid duplicate seed rows.
    """
    obj = model.query.filter_by(**kwargs).first()
    if obj:
        return obj, False
    params = {**(defaults or {}), **kwargs}
    obj = model(**params)
    db.session.add(obj)
    return obj, True


def _checksum11(body: str) -> int:
    """
    Same checksum scheme as registration validation:
      - Map digits 0-9 -> 0..9
      - Map letters A-Z -> 10..35
      - Sum(value * position) for each char (1-based), then % 11
      - Check char: 'X' if checksum == 10 else the digit (0-9)
    """
    val = 0
    for i, ch in enumerate(body, start=1):
        if ch.isdigit():
            v = ord(ch) - 48
        else:
            v = 10 + (ord(ch.upper()) - 65)
        val += v * i
    return val % 11


def make_lic(body: str) -> str:
    """
    Build a valid licence number from the given body (5-9 alnum is recommended).
    Ensures final string length is 6..10 and last char is a valid check char.
    """
    body = "".join(ch for ch in body.strip().replace(" ", "") if ch.isalnum())
    if not (5 <= len(body) <= 9):
        body = "VIC001"
    chk = _checksum11(body)
    return body + ("X" if chk == 10 else str(chk))


# -------------------------------------------------------------------
# Seeding
# -------------------------------------------------------------------
def init_database(app):
    """
    Create tables and seed baseline data for local development/demo:
      - Roles: voter/delegate/manager
      - Regions
      - Users: admin (manager), delegate1 (delegate), voter1 (voter), lix (voter)
      - Electoral roll for voter1 (active + verified in Sydney)
      - Test voters (110 fake voters for development)
      - Candidates in Sydney
    All seeded users are set to `approved` to simplify local testing.
    """
    with app.app_context():
        # Wait for database to be ready
        wait_for_db()

        # 1) create tables
        try:
            db.create_all()
        except Exception as e:
            print(f"❌ Failed to create database tables: {e}")
            print("💡 This may be a schema mismatch. Reset the DB or run migrations.")
            raise

        # 2) seed roles + regions
        try:
            for name, desc in [
                ("voter", "Can cast one vote"),
                ("delegate", "Manages candidates, cannot vote"),
                ("manager", "System admin, cannot vote"),
            ]:
                get_or_create(Role, name=name, defaults={"description": desc})

            for rname in ["Sydney", "VIC east", "VIC west", "NSW", "SA"]:
                get_or_create(Region, name=rname)

            db.session.flush()  # ensure IDs exist for FKs
        except Exception as e:
            print(f"❌ Failed to seed roles/regions: {e}")
            db.session.rollback()
            raise

        # Quick lookups
        voter_role = Role.query.filter_by(name="voter").first()
        delegate_role = Role.query.filter_by(name="delegate").first()
        manager_role = Role.query.filter_by(name="manager").first()
        sydney = Region.query.filter_by(name="Sydney").first()
        vic_east = Region.query.filter_by(name="VIC east").first()

        # 3) seed users (set account_status=approved)
        try:
            # --- admin (manager) ---
            admin = User.query.filter_by(username="admin").first()
            if not admin:
                admin = User(
                    username="admin",
                    email="secsoftsysa3@myyahoo.com",
                    driver_lic_no=make_lic("ADMIN01"),
                    driver_lic_state="VIC",
                    has_voted=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    account_status="approved",
                )
                admin.role = manager_role
                admin.set_password("Admin@123456!")  # Meet password policy requirements
                db.session.add(admin)
            else:
                # ensure important fields are present/consistent
                admin.email = "secsoftsysa3@myyahoo.com"
                admin.driver_lic_no = admin.driver_lic_no or make_lic("ADMIN01")
                admin.driver_lic_state = admin.driver_lic_state or "VIC"
                if not admin.role:
                    admin.role = manager_role
                if not admin.account_status:
                    admin.account_status = "approved"

            # --- delegate1 (delegate) ---
            delegate1 = User.query.filter_by(username="delegate1").first()
            if not delegate1:
                delegate1 = User(
                    username="delegate1",
                    email="delegate1@voting.com",
                    driver_lic_no=make_lic("DELEG01"),
                    driver_lic_state="NSW",
                    has_voted=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    account_status="approved",
                )
                delegate1.role = delegate_role
                delegate1.set_password("Delegate@123!")
                db.session.add(delegate1)
            else:
                delegate1.driver_lic_no = delegate1.driver_lic_no or make_lic("DELEG01")
                delegate1.driver_lic_state = delegate1.driver_lic_state or "NSW"
                if not delegate1.role:
                    delegate1.role = delegate_role
                if not delegate1.account_status:
                    delegate1.account_status = "approved"

            # --- voter1 (voter) ---
            voter1 = User.query.filter_by(username="voter1").first()
            if not voter1:
                voter1 = User(
                    username="voter1",
                    email="voter1@voting.com",
                    driver_lic_no=make_lic("VOTER01"),
                    driver_lic_state="NSW",
                    has_voted=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    account_status="approved",
                )
                voter1.role = voter_role
                voter1.set_password("Password@123!")
                db.session.add(voter1)
            else:
                voter1.driver_lic_no = voter1.driver_lic_no or make_lic("VOTER01")
                voter1.driver_lic_state = voter1.driver_lic_state or "NSW"
                if not voter1.role:
                    voter1.role = voter_role
                if not voter1.account_status:
                    voter1.account_status = "approved"

            # --- lix (voter) ---
            lix = User.query.filter_by(username="lix").first()
            if not lix:
                lix = User(
                    username="lix",
                    email="2508027683@qq.com",
                    driver_lic_no=make_lic("LIX0001"),
                    driver_lic_state="VIC",
                    has_voted=False,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    account_status="approved",
                )
                lix.role = voter_role
                lix.set_password("Password@123!")
                db.session.add(lix)
            else:
                lix.driver_lic_no = lix.driver_lic_no or make_lic("LIX0001")
                lix.driver_lic_state = lix.driver_lic_state or "VIC"
                if not lix.role:
                    lix.role = voter_role
                if not lix.account_status:
                    lix.account_status = "approved"

            # Create 110 test voters for development (always enabled for local dev)
            create_test_voters = os.environ.get('CREATE_TEST_VOTERS', 'true').lower() == 'true'
            is_testing_env = app.config.get('TESTING', False)
            if create_test_voters and TEST_VOTERS_AVAILABLE:
                print("🧪 Creating 110 test voters for development purposes...")
                test_voters_data = get_test_voters()
                created_count = 0

                # Fast-path: if no test voters exist, bulk add without per-user existence checks
                existing_count = User.query.filter(User.username.like('testvoter%')).count()
                if existing_count == 0:
                    users = []
                    ts = datetime.utcnow()
                    for voter_data in test_voters_data:
                        users.append(User(
                            username=voter_data['username'],
                            email=voter_data['email'],
                            driver_lic_no=voter_data['driver_license_number'],
                            driver_lic_state=voter_data['state'],
                            role=voter_role,
                            has_voted=False,
                            created_at=ts,
                            account_status="approved",
                            password_hash=generate_password_hash(
                                voter_data['password'],
                                method='pbkdf2:sha256:1' if is_testing_env else 'pbkdf2:sha256'
                            ),
                            password_changed_at=ts,
                            failed_login_attempts=0,
                            account_locked_until=None,
                        ))
                    db.session.add_all(users)
                    created_count = len(users)
                else:
                    for voter_data in test_voters_data:
                        # Check if test voter already exists
                        if not User.query.filter_by(username=voter_data['username']).first():
                            test_user = User(
                                username=voter_data['username'],
                                email=voter_data['email'],
                                driver_lic_no=voter_data['driver_license_number'],
                                driver_lic_state=voter_data['state'],
                                role=voter_role,
                                has_voted=False,
                                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                                account_status="approved",
                            )
                            # For test voters, bypass strength validation to honor test expectations
                            test_user.password_hash = generate_password_hash(
                                voter_data['password'],
                                method='pbkdf2:sha256:1' if is_testing_env else 'pbkdf2:sha256'
                            )
                            test_user.password_changed_at = datetime.utcnow()
                            test_user.failed_login_attempts = 0
                            test_user.account_locked_until = None
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
            print("💡 Check User/Role schema. If mismatched, reset DB and re-run.")
            db.session.rollback()
            raise

        try:
            # 5) electoral roll entry for voter1 (active & verified in Sydney)
            if voter1 and not ElectoralRoll.query.filter_by(user_id=voter1.id).first():
                er = ElectoralRoll(
                    roll_number="ER-0001",
                    driver_license_number=voter1.driver_lic_no,  # keep consistent
                    full_name="Voter One",
                    date_of_birth=date(1990, 5, 10),
                    address_line1="1 King St",
                    suburb="Sydney",
                    state="NSW",
                    postcode="2000",
                    region_id=sydney.id,
                    status="active",
                    verified=True,
                    verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    user_id=voter1.id,
                )
                db.session.add(er)

            # Create electoral roll entries for test voters if they were created
            if create_test_voters and TEST_VOTERS_AVAILABLE:
                print("🗳️  Creating electoral roll entries for test voters...")
                test_voters_data = get_test_voters()
                regions = Region.query.all()  # Get all available regions
                roll_entries_created = 0
                
                # Fast-path if fresh DB: assume no roll entries exist
                existing_rolls = ElectoralRoll.query.filter(ElectoralRoll.roll_number.like('ER-1%')).count()
                if existing_rolls == 0:
                    # Build a map of username -> user.id to avoid per-item queries
                    users_index = {u.username: u.id for u in User.query.filter(User.username.like('testvoter%')).all()}
                    ts = datetime.utcnow()
                    bulk_rolls = []
                    for voter_data in test_voters_data:
                        uid = users_index.get(voter_data['username'])
                        if uid:
                            random_region = regions[hash(voter_data['username']) % len(regions)]
                            bulk_rolls.append(ElectoralRoll(
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
                                verified_at=ts,
                                user_id=uid,
                            ))
                    db.session.add_all(bulk_rolls)
                    roll_entries_created = len(bulk_rolls)
                else:
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
                                verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
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
                        #Sydney candidates
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
                        #VIC east candidates
                        Candidate(
                            name="Edward Green",
                            party="Labor Party",
                            position="House of Representatives",
                            region_id=vic_east.id,
                        ),
                        Candidate(
                            name="Alice White",
                            party="Liberal Party",
                            position="House of Representatives",
                            region_id=vic_east.id,
                        ),
                        Candidate(
                            name="Tom Black",
                            party="Greens",
                            position="House of Representatives",
                            region_id=vic_east.id,
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

        # 6) commit
        try:
            db.session.commit()
        except Exception as e:
            print(f"❌ Failed to commit database changes: {e}")
            db.session.rollback()
            raise

        print(" 🧀✅ Database initialized")
        print(" 🧑‍💻 Logins you can use:")
        print("  manager  → admin / Admin@123456!")
        print("  delegate → delegate1 / Delegate@123!")
        print("  voter    → voter1 / Password@123!")
        print("  voter    → lix / Password@123!")
        print(f" 🗳️  Plus {len(get_test_voters()) if TEST_VOTERS_AVAILABLE else 0} test voters: testvoter001-{len(get_test_voters()) if TEST_VOTERS_AVAILABLE else 0:03d} / TestPass@123!")


if __name__ == "__main__":
    # Allow running this file directly for quick manual seeding
    from app import create_app
    app = create_app()
    init_database(app)