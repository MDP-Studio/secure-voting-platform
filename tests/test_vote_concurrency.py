"""
Concurrent double-vote stress test.

This test fires N simultaneous calls to ``cast_anonymous_vote()`` for the
SAME user from different threads, then asserts that exactly ONE ballot was
recorded regardless of how many threads raced.

Why this matters:
-----------------
The vote service uses ``SELECT ... FOR UPDATE`` (pessimistic row locking)
on the User record to prevent a TOCTOU race where two concurrent requests
both read ``has_voted=False`` before either commits.  Sequential unit tests
cannot catch this class of bug — you need actual concurrency.

Design:
-------
We test at the service layer (``cast_anonymous_vote``) rather than via HTTP
because Flask's test client doesn't support true concurrent authenticated
sessions.  The service function is where the lock lives, so this directly
validates the critical section.

SQLite note:
------------
SQLite serializes all writers via a database-level lock, so FOR UPDATE is
technically a no-op.  This test still validates the application-layer logic
under concurrent load.  For production-grade validation on MySQL/PostgreSQL,
run against the Docker stack with a load testing tool (e.g., locust).
"""

import pytest
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from app import db, create_app
from app.models import User, Vote, Candidate, Election
from app.vote_service import cast_anonymous_vote, AlreadyVotedError


# Number of concurrent vote attempts.  Higher = more aggressive.
CONCURRENT_THREADS = 10


class TestVoteConcurrency:
    """Stress test: fire concurrent vote calls for the same user."""

    def test_concurrent_double_vote_at_service_layer(self, app):
        """
        Fire CONCURRENT_THREADS simultaneous ``cast_anonymous_vote()`` calls
        for the same user.  Assert exactly 1 ballot is recorded.
        """
        with app.app_context():
            candidate = Candidate.query.first()
            voter = User.query.filter_by(username='voter1').first()
            assert voter is not None
            assert voter.has_voted is False
            voter_id = voter.id
            candidate_id = candidate.id

        successes = []
        failures = []
        lock = threading.Lock()

        def attempt_vote():
            """Each thread gets its own app context and DB session."""
            with app.app_context():
                try:
                    user = db.session.get(User, voter_id)
                    cand = db.session.get(Candidate, candidate_id)
                    cast_anonymous_vote(db, user, cand)
                    with lock:
                        successes.append(True)
                except (AlreadyVotedError, Exception) as e:
                    with lock:
                        failures.append(str(e))

        with ThreadPoolExecutor(max_workers=CONCURRENT_THREADS) as pool:
            futures = [pool.submit(attempt_vote) for _ in range(CONCURRENT_THREADS)]
            for f in as_completed(futures):
                f.result()  # propagate any unexpected exceptions

        # --- Critical assertion ---
        with app.app_context():
            vote_count = Vote.query.count()
            assert vote_count == 1, (
                f"TOCTOU RACE CONDITION: Expected exactly 1 vote, "
                f"but found {vote_count}. Pessimistic lock failed. "
                f"Successes: {len(successes)}, Failures: {len(failures)}"
            )

            voter = db.session.get(User, voter_id)
            assert voter.has_voted is True

        assert len(successes) == 1, (
            f"Exactly 1 thread should succeed, got {len(successes)}"
        )
        assert len(failures) == CONCURRENT_THREADS - 1, (
            f"Expected {CONCURRENT_THREADS - 1} failures, got {len(failures)}"
        )

    def test_concurrent_different_users_both_succeed(self, app):
        """
        Two different users voting concurrently should both succeed.
        The row lock is per-user, not global.
        """
        with app.app_context():
            from app.models import Role, Region, ElectoralRoll
            from datetime import date

            voter_role = Role.query.filter_by(name='voter').first()
            region = Region.query.first()

            voter2 = User(
                username='voter2_concurrent',
                email='voter2_concurrent@test.com',
                driver_lic_no='CON00017',
                driver_lic_state='NSW',
                account_status='approved',
            )
            voter2.role_id = voter_role.id
            voter2.set_password('Password@123!')
            db.session.add(voter2)
            db.session.flush()

            enrolment = ElectoralRoll(
                roll_number='CONC002',
                driver_license_number='CON00017',
                full_name='Concurrent Voter 2',
                date_of_birth=date(1990, 1, 1),
                address_line1='456 Test St',
                suburb='Test Suburb',
                state='NSW',
                postcode='2000',
                region=region,
                status='active',
                verified=True,
                user=voter2
            )
            db.session.add(enrolment)
            db.session.commit()

            candidate = Candidate.query.first()
            voter1 = User.query.filter_by(username='voter1').first()
            voter1_id = voter1.id
            voter2_id = voter2.id
            candidate_id = candidate.id

        results = {}

        def vote_as(user_id, label):
            with app.app_context():
                try:
                    user = db.session.get(User, user_id)
                    cand = db.session.get(Candidate, candidate_id)
                    cast_anonymous_vote(db, user, cand)
                    results[label] = True
                except Exception:
                    results[label] = False

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(vote_as, voter1_id, 'voter1')
            f2 = pool.submit(vote_as, voter2_id, 'voter2')
            f1.result()
            f2.result()

        assert results.get('voter1') is True, "voter1 should succeed"
        assert results.get('voter2') is True, "voter2 should succeed"

        with app.app_context():
            total_votes = Vote.query.count()
            assert total_votes == 2, f"Expected 2 votes from 2 users, got {total_votes}"
