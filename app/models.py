from datetime import datetime
from . import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
   # driver_lic_no = db.Column(db.String(32), unique=True, nullable=False, index=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    has_voted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class Candidate(db.Model):
    __tablename__ = "candidate"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    party = db.Column(db.String(120), nullable=True)          # added
    position = db.Column(db.String(120), nullable=False)
    constituency = db.Column(db.String(120), nullable=True)   # added
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Vote(db.Model):
    __tablename__ = "vote"
    __table_args__ = (
        # Enforce one vote per user at the database level to prevent duplicates
        db.UniqueConstraint('user_id', name='uq_vote_user_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.String(120), nullable=False)
    vote_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Note: additional constraints should be added above in the single __table_args__ block

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))