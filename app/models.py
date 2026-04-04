# app/models.py
from datetime import datetime, timezone
import hashlib
import re
from . import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .security.password_validator import validate_password_strength, PasswordValidationError
from .security.encryption import EncryptedType
from sqlalchemy import event

def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

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
    # Store the licence number encrypted at rest; use a deterministic SHA-256 hash
    # for uniqueness and lookup to avoid leaking plaintext while supporting queries.
    driver_lic_no = db.Column(EncryptedType(length=255), nullable=False)
    driver_lic_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    driver_lic_state = db.Column(db.String(8), nullable=True)  # e.g., VIC/NSW/QLD/...

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    # one role -> many users
    role = db.relationship("Role", backref=db.backref("users", lazy="dynamic"))

    # Admin approval state (String, no Enum)
    account_status = db.Column(db.String(20), nullable=False, default="pending")

    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    has_voted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Password policy fields
    password_changed_at = db.Column(db.DateTime, default=utcnow_naive)
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
        self.password_changed_at = utcnow_naive()
        
        # Reset failed login attempts when password is changed
        self.failed_login_attempts = 0
        self.account_locked_until = None

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
    
    def is_account_locked(self) -> bool:
        """Check if account is currently locked due to failed login attempts."""
        if self.account_locked_until is None:
            return False
        return utcnow_naive() < self.account_locked_until
    
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
            self.account_locked_until = utcnow_naive() + timedelta(minutes=lockout_minutes)
    
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
        return utcnow_naive() > expiration_date

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


# ---- Helpers for deterministic licence hashing (blind indexing) ----
_WS_RE = re.compile(r"\s+")

def _normalize_lic(lic: str | None) -> str | None:
    if not lic:
        return None
    # remove whitespace and uppercase for stable hashing
    return _WS_RE.sub("", str(lic)).upper()


def _get_hash_pepper() -> bytes:
    """
    Return the LICENSE_HASH_PEPPER from the environment.
    This high-entropy secret is mixed into HMAC-based blind indexes
    so that raw SHA-256 rainbow tables are useless.
    """
    import os
    pepper = os.environ.get("LICENSE_HASH_PEPPER", "")
    if not pepper:
        # Fall back to SECRET_KEY if pepper not set (dev convenience).
        # Production deployments MUST set LICENSE_HASH_PEPPER.
        from flask import current_app
        try:
            pepper = current_app.config.get("SECRET_KEY", "fallback-dev-pepper")
        except RuntimeError:
            pepper = "fallback-dev-pepper"
    return pepper.encode("utf-8")


def _hash_lic(lic: str | None) -> str | None:
    """
    Blind index: HMAC-SHA256 keyed with an application-wide pepper.
    Produces a deterministic but brute-force-resistant hash suitable
    for duplicate-detection queries without exposing plaintext.
    """
    import hmac as _hmac
    norm = _normalize_lic(lic)
    if not norm:
        return None
    return _hmac.new(
        key=_get_hash_pepper(),
        msg=norm.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


# Keep driver_lic_hash in sync on insert/update
@event.listens_for(User, "before_insert")
def _user_set_lic_hash_before_insert(mapper, connection, target: "User"):
    target.driver_lic_hash = _hash_lic(getattr(target, "driver_lic_no", None)) or target.driver_lic_hash


@event.listens_for(User, "before_update")
def _user_set_lic_hash_before_update(mapper, connection, target: "User"):
    # Recompute when the plaintext value changes
    target.driver_lic_hash = _hash_lic(getattr(target, "driver_lic_no", None)) or target.driver_lic_hash


# ---- Electoral Roll ----
class ElectoralRoll(db.Model):
    __tablename__ = "electoral_roll"
    id = db.Column(db.Integer, primary_key=True)

    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    driver_license_number = db.Column(EncryptedType(length=255), unique=True, nullable=False)
    # Deterministic hash for uniqueness and lookups that do not leak plaintext
    driver_license_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)

    full_name = db.Column(EncryptedType(length=255), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    address_line1 = db.Column(EncryptedType(length=255), nullable=False)
    address_line2 = db.Column(EncryptedType(length=255))
    suburb = db.Column(EncryptedType(length=255), nullable=False)
    state = db.Column(EncryptedType(length=50), nullable=False)
    postcode = db.Column(EncryptedType(length=50), nullable=False)

    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    region = db.relationship("Region")

    # <-- CHANGED: use String instead of Enum to avoid enum-mismatch errors
    status = db.Column(db.String(20), nullable=False, default="active")
    verified = db.Column(db.Boolean, nullable=False, default=False)
    verified_at = db.Column(db.DateTime)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    user = db.relationship("User", backref=db.backref("enrolment", uselist=False))

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def __repr__(self):
        return f"<ElectoralRoll {self.roll_number} {self.full_name}>"


# Keep electoral roll licence hash in sync on insert/update
@event.listens_for(ElectoralRoll, "before_insert")
def _roll_set_lic_hash_before_insert(mapper, connection, target: "ElectoralRoll"):
    target.driver_license_hash = _hash_lic(getattr(target, "driver_license_number", None)) or target.driver_license_hash


@event.listens_for(ElectoralRoll, "before_update")
def _roll_set_lic_hash_before_update(mapper, connection, target: "ElectoralRoll"):
    target.driver_license_hash = _hash_lic(getattr(target, "driver_license_number", None)) or target.driver_license_hash


# ---- Elections ----
class Election(db.Model):
    __tablename__ = "election"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft, open, closed
    open_at = db.Column(db.DateTime, nullable=True)
    close_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    @property
    def is_open(self):
        if self.status != "open":
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if self.open_at and now < self.open_at:
            return False
        if self.close_at and now > self.close_at:
            return False
        return True

    def __repr__(self):
        return f"<Election {self.name} ({self.status})>"


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

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Candidate {self.name} - {self.position} ({self.region.name})>"


# ---- Votes (anonymous ballots) ----
class Vote(db.Model):
    """
    Anonymous ballot record.

    Each ballot carries a cryptographically random ``voter_token``
    (``secrets.token_hex(32)``) with NO mathematical relationship to
    the voter's identity.  There is no stored foreign key, HMAC, or
    deterministic derivation linking a Vote back to a User.

    Double-vote prevention is enforced by the ``VoteReceipt`` table
    (UNIQUE constraint on user_id) which is inserted in the same
    transaction as the ballot.  If a concurrent insert violates the
    unique constraint, the entire transaction — including the anonymous
    ballot — is rolled back.

    Limitation: the server process transiently knows both identity and
    ballot during the HTTP request.  True end-to-end verifiable anonymity
    (blind signatures, homomorphic tallying) requires a multi-party
    protocol beyond the scope of a server-side web application.
    """
    __tablename__ = "vote"
    id = db.Column(db.Integer, primary_key=True)
    voter_token = db.Column(db.String(64), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidate.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    position = db.Column(db.String(120), nullable=False)
    vote_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=utcnow_naive)


# ---- Vote Receipts (double-vote prevention) ----
class VoteReceipt(db.Model):
    """
    Database-level one-vote-per-user enforcement.

    This table stores ONLY the fact that a user has voted — NOT which
    candidate they voted for.  The UNIQUE constraint on user_id is the
    authoritative guard against double-voting, surviving any application-
    level race conditions (TOCTOU).

    Inserted in the same transaction as the anonymous Vote record.  If a
    concurrent thread tries to insert a duplicate receipt, the DB rejects
    the entire transaction, rolling back the ballot as well.
    """
    __tablename__ = "vote_receipt"
    __table_args__ = (
        db.UniqueConstraint('user_id', name='uq_vote_receipt_user'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    voted_at = db.Column(db.DateTime, default=utcnow_naive)

# ---- Blind Signature Tokens ----
class BlindSignatureToken(db.Model):
    """
    Tracks blind signature token issuance for the anonymous voting protocol.

    Issued during Phase 1 (authenticated token request). The voter's
    identity is linked to the token, but the ballot content is blinded
    and invisible to the server. During Phase 2 (anonymous ballot cast),
    the token is matched via ballot_nonce_hash and marked redeemed.

    UNIQUE(user_id) prevents a voter from obtaining multiple tokens.
    UNIQUE(ballot_nonce_hash) prevents replay of the same ballot.
    """
    __tablename__ = "blind_signature_token"
    __table_args__ = (
        db.UniqueConstraint('user_id', name='uq_blind_sig_token_user'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ballot_nonce_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    issued_at = db.Column(db.DateTime, default=utcnow_naive)
    redeemed = db.Column(db.Boolean, default=False, nullable=False)
    redeemed_at = db.Column(db.DateTime, nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
