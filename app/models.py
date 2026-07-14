import logging
# app/models.py
from datetime import datetime, timezone
import hashlib
import re
from . import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .security.password_validator import validate_password_strength, PasswordValidationError
from .security.encryption import EncryptedType
from sqlalchemy import event, inspect as sqlalchemy_inspect


# Physical VARCHAR capacities for Base64-encoded svpii:v1 envelopes. The long
# capacity covers 255 Unicode code points at four UTF-8 bytes each, plus nonce,
# tag, marker, and Base64 expansion. The short capacity does the same for the
# legacy 50-character state/postcode limits.
ENCRYPTED_LICENCE_COLUMN_LENGTH = 255
ENCRYPTED_LONG_PII_COLUMN_LENGTH = 1536
ENCRYPTED_SHORT_PII_COLUMN_LENGTH = 512

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
    # Store the licence number encrypted at rest; use a keyed HMAC-SHA256 blind
    # index for uniqueness and lookup without querying randomized ciphertext.
    driver_lic_no = db.Column(
        EncryptedType(length=ENCRYPTED_LICENCE_COLUMN_LENGTH),
        nullable=False,
    )
    driver_lic_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    driver_lic_state = db.Column(db.String(8), nullable=True)  # e.g., VIC/NSW/QLD/...

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    # one role -> many users
    role = db.relationship("Role", backref=db.backref("users", lazy="dynamic"))

    # Admin approval state (String, no Enum)
    account_status = db.Column(db.String(20), nullable=False, default="pending")

    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    
    # Password policy fields
    password_changed_at = db.Column(db.DateTime, default=utcnow_naive)
    # Monotonic authentication epoch. Every password change increments this
    # value so all previously issued JWTs and password-reset links fail closed.
    session_version = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
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
        self.session_version = int(self.session_version or 0) + 1
        
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
        from flask import current_app

        if not current_app.config.get("TESTING"):
            raise RuntimeError("LICENSE_HASH_PEPPER is required outside test mode")
        pepper = current_app.config.get("SECRET_KEY")
        if not pepper:
            raise RuntimeError("A test SECRET_KEY is required for licence hashing")
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
    """Recompute the blind index only for a real decrypted licence change."""
    history = sqlalchemy_inspect(target).attrs.driver_lic_no.history
    if not history.has_changes():
        return

    current = history.added[0] if history.added else target.driver_lic_no
    previous = history.deleted[0] if history.deleted else None
    if previous is not None and _normalize_lic(previous) == _normalize_lic(current):
        return

    target.driver_lic_hash = _hash_lic(current) or target.driver_lic_hash


# ---- Electoral Roll ----
class ElectoralRoll(db.Model):
    __tablename__ = "electoral_roll"
    id = db.Column(db.Integer, primary_key=True)

    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    driver_license_number = db.Column(
        EncryptedType(length=ENCRYPTED_LICENCE_COLUMN_LENGTH),
        nullable=False,
    )
    # Deterministic hash for uniqueness and lookups that do not leak plaintext
    driver_license_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)

    full_name = db.Column(
        EncryptedType(length=ENCRYPTED_LONG_PII_COLUMN_LENGTH),
        nullable=False,
    )
    date_of_birth = db.Column(db.Date, nullable=False)
    address_line1 = db.Column(
        EncryptedType(length=ENCRYPTED_LONG_PII_COLUMN_LENGTH),
        nullable=False,
    )
    address_line2 = db.Column(
        EncryptedType(length=ENCRYPTED_LONG_PII_COLUMN_LENGTH)
    )
    suburb = db.Column(
        EncryptedType(length=ENCRYPTED_LONG_PII_COLUMN_LENGTH),
        nullable=False,
    )
    # Versioned AEAD envelopes include nonce, tag, format marker, and Base64
    # expansion, so short plaintext fields still need full ciphertext capacity.
    state = db.Column(
        EncryptedType(length=ENCRYPTED_SHORT_PII_COLUMN_LENGTH),
        nullable=False,
    )
    postcode = db.Column(
        EncryptedType(length=ENCRYPTED_SHORT_PII_COLUMN_LENGTH),
        nullable=False,
    )

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
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'open', 'closed')",
            name="ck_election_status",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft, open, closed
    open_at = db.Column(db.DateTime, nullable=True)
    close_at = db.Column(db.DateTime, nullable=True)
    blind_signing_key_id = db.Column(db.String(64), nullable=True)
    blind_key_recovery_required = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.false(),
    )
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    @property
    def is_open(self):
        if self.status != "open" or self.blind_key_recovery_required:
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
    __table_args__ = (
        db.UniqueConstraint("id", "election_id", name="uq_candidate_id_election"),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    party = db.Column(db.String(120), nullable=True)
    position = db.Column(db.String(120), nullable=False)

    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    region = db.relationship("Region")

    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    election = db.relationship(
        "Election",
        backref=db.backref("candidates", lazy="dynamic", cascade="all, delete-orphan"),
    )

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

    The supported ballot flow uses a one-time identity-side authorization at
    issuance and an identity-free ``SpentBallotNullifier`` in the cast
    transaction. Neither identity-side table stores the candidate choice.

    Limitation: blind submission still has network and timing metadata. True
    end-to-end verifiability and coercion resistance require a broader protocol.
    """
    __tablename__ = "vote"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["candidate_id", "election_id"],
            ["candidate.id", "candidate.election_id"],
            name="fk_vote_candidate_election",
            ondelete="CASCADE",
        ),
        db.UniqueConstraint("voter_token", name="uq_vote_voter_token"),
    )
    id = db.Column(db.Integer, primary_key=True)
    voter_token = db.Column(db.String(64), nullable=False)
    candidate_id = db.Column(db.Integer, nullable=False, index=True)
    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = db.Column(db.String(120), nullable=False)
    vote_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=utcnow_naive)


# ---- Legacy direct-vote receipts (migration compatibility only) ----
class VoteReceipt(db.Model):
    """
    Historical identity-side receipt from the retired direct ballot path.

    This table stores ONLY the fact that a user has voted — NOT which
    candidate they voted for. The UNIQUE constraint on user_id plus
    election_id is the authoritative same-election guard against
    double-voting, surviving application-level race conditions (TOCTOU).

    New ballots do not create this row. The record remains so elections that
    received direct ballots before the anonymity-only cutover cannot issue a
    second blind authorization to the same voter.
    """
    __tablename__ = "vote_receipt"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "election_id",
            name="uq_vote_receipt_user_election",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = db.relationship(
        "User",
        backref=db.backref("vote_receipts", lazy="dynamic"),
    )
    voted_at = db.Column(db.DateTime, default=utcnow_naive)

# ---- Blind Signature Tokens ----
class BlindSignatureToken(db.Model):
    """
    Identity-side record that exactly one blind signature was issued.

    This row deliberately contains no ballot nonce, signature, candidate, cast
    timestamp, or redemption state. That separation prevents an anonymous
    ballot from being deterministically joined back to the authenticated voter.
    A lost authorization fails closed instead of allowing a second ballot.
    """
    __tablename__ = "blind_signature_token"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "election_id",
            name="uq_blind_sig_token_user_election",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class SpentBallotNullifier(db.Model):
    """Identity-free replay guard for anonymously submitted ballots."""

    __tablename__ = "spent_ballot_nullifier"
    __table_args__ = (
        db.UniqueConstraint(
            "election_id",
            "nullifier_hash",
            name="uq_spent_nullifier_election_hash",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nullifier_hash = db.Column(db.String(64), nullable=False)
    spent_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)


class ResultSigningPublicKey(db.Model):
    """Immutable local result-signing public-key archive by fingerprint."""

    __tablename__ = "result_signing_public_key"
    key_id = db.Column(db.String(64), primary_key=True)
    algorithm = db.Column(db.String(64), nullable=False)
    public_key_pem = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)


@event.listens_for(ResultSigningPublicKey, "before_update")
@event.listens_for(ResultSigningPublicKey, "before_delete")
def _prevent_result_key_archive_mutation(mapper, connection, target):
    raise ValueError("Archived result-signing public keys are immutable")


class SignedElectionResult(db.Model):
    """Durable, election-scoped signed result projection."""

    __tablename__ = "signed_election_result"
    __table_args__ = (
        db.UniqueConstraint(
            "election_id",
            name="uq_signed_election_result_election",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(
        db.Integer,
        db.ForeignKey("election.id", ondelete="CASCADE"),
        nullable=False,
    )
    payload = db.Column(db.Text, nullable=False)
    signature = db.Column(db.Text, nullable=False)
    signer_backend = db.Column(db.String(32), nullable=False)
    signature_algorithm = db.Column(db.String(64), nullable=False)
    signing_key_id = db.Column(db.String(255), nullable=False)
    signing_key_version = db.Column(db.Integer, nullable=True)
    signed_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    signed_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    election = db.relationship("Election")


@event.listens_for(SignedElectionResult, "before_update")
@event.listens_for(SignedElectionResult, "before_delete")
def _prevent_signed_result_mutation(mapper, connection, target):
    raise ValueError("Persisted signed election results are immutable")


class OtpChallenge(db.Model):
    """Server-side, replay-resistant OTP verification state."""

    __tablename__ = "otp_challenge"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "purpose",
            name="uq_otp_challenge_user_purpose",
        ),
        db.CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= 5",
            name="ck_otp_challenge_failed_attempts",
        ),
    )
    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose = db.Column(db.String(32), nullable=False)
    code_digest = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
