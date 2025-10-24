# app/models.py
from datetime import datetime
from . import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .security.password_validator import validate_password_strength, PasswordValidationError

# ---- Roles ----
class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)   # voter, delegate, manager
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<Role {self.name}>"


# ---- Regions ----
class Region(db.Model):
    __tablename__ = "regions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f"<Region {self.name}>"


# ---- Users ----
class User(UserMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Driver licence (used for identity binding)
    driver_lic_no = db.Column(db.String(32), unique=True, nullable=False, index=True)
    driver_lic_state = db.Column(db.String(8), nullable=True)  # e.g., VIC/NSW/QLD/...

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    # one role -> many users
    role = db.relationship("Role", backref=db.backref("users", lazy="dynamic"))

    # Admin approval state (String, no Enum)
    account_status = db.Column(db.String(20), nullable=False, default="pending")

    has_voted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Password policy fields
    password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)

    # helpers
    def set_password(self, password: str):
        """
        Set the user's password after validating it meets security requirements.
        
        Args:
            password (str): The password to set
            
        Raises:
            PasswordValidationError: If password does not meet requirements
        """
        # Validate password strength
        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            raise PasswordValidationError(error_message)
        
        # Hash and store the password
        self.password_hash = generate_password_hash(password)
        
        # Update password change timestamp
        self.password_changed_at = datetime.utcnow()
        
        # Reset failed login attempts when password is changed
        self.failed_login_attempts = 0
        self.account_locked_until = None

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
    
    def is_account_locked(self) -> bool:
        """Check if account is currently locked due to failed login attempts."""
        if self.account_locked_until is None:
            return False
        return datetime.utcnow() < self.account_locked_until
    
    def record_failed_login(self, max_attempts: int = 5, lockout_minutes: int = 30):
        """
        Record a failed login attempt and lock account if threshold is reached.
        
        Args:
            max_attempts: Maximum failed login attempts before lockout (default: 5)
            lockout_minutes: Duration of account lockout in minutes (default: 30)
        """
        from datetime import timedelta
        
        self.failed_login_attempts += 1
        
        if self.failed_login_attempts >= max_attempts:
            self.account_locked_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)
    
    def reset_failed_logins(self):
        """Reset failed login counter and unlock account."""
        self.failed_login_attempts = 0
        self.account_locked_until = None
    
    def is_password_expired(self, expiration_days: int = 90) -> bool:
        """
        Check if password has expired based on age.
        
        Args:
            expiration_days: Number of days before password expires (default: 90)
            
        Returns:
            bool: True if password is expired, False otherwise
        """
        from datetime import timedelta
        
        if self.password_changed_at is None:
            # If no timestamp, consider it expired for safety
            return True
        
        expiration_date = self.password_changed_at + timedelta(days=expiration_days)
        return datetime.utcnow() > expiration_date

    def has_role(self, *names):
        return self.role and self.role.name in names

    @property
    def is_voter(self):
        return self.has_role("voter")

    @property
    def is_delegate(self):
        return self.has_role("delegate")

    @property
    def is_manager(self):
        return self.has_role("manager")

    @property
    def is_approved(self) -> bool:
        return (self.account_status or "").lower() == "approved"

    def __repr__(self):
        return f"<User {self.username} ({self.role.name if self.role else 'no-role'})>"


# ---- Electoral Roll ----
class ElectoralRoll(db.Model):
    __tablename__ = "electoral_roll"
    id = db.Column(db.Integer, primary_key=True)

    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    driver_license_number = db.Column(db.String(30), unique=True, nullable=False)

    full_name = db.Column(db.String(150), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    address_line1 = db.Column(db.String(150), nullable=False)
    address_line2 = db.Column(db.String(150))
    suburb = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    postcode = db.Column(db.String(10), nullable=False)

    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    region = db.relationship("Region")

    # <-- CHANGED: use String instead of Enum to avoid enum-mismatch errors
    status = db.Column(db.String(20), nullable=False, default="active")
    verified = db.Column(db.Boolean, nullable=False, default=False)
    verified_at = db.Column(db.DateTime)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    user = db.relationship("User", backref=db.backref("enrolment", uselist=False))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ElectoralRoll {self.roll_number} {self.full_name}>"


# ---- Candidates ----
class Candidate(db.Model):
    __tablename__ = "candidate"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    party = db.Column(db.String(120), nullable=True)
    position = db.Column(db.String(120), nullable=False)

    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    region = db.relationship("Region")

    votes = db.relationship(
        "Vote",
        backref=db.backref("candidate", lazy="joined"),
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Candidate {self.name} - {self.position} ({self.region.name})>"


# ---- Votes ----
class Vote(db.Model):
    __tablename__ = "vote"
    __table_args__ = (
        # Enforce one vote per user at the database level to prevent duplicates
        db.UniqueConstraint('user_id', name='uq_vote_user_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidate.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    position = db.Column(db.String(120), nullable=False)
    vote_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
