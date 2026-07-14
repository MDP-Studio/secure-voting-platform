import base64
import os
import re
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from flask_login import login_user

from app import db
from app import models
from app.models import ElectoralRoll, User
from app.security.encryption import (
    ChaChaEncryptionService,
    LegacyPIIMigrationError,
    PIIDecryptionError,
)


def is_base64_padded(s: str) -> bool:
    if not isinstance(s, str):
        return False
    prefix = ChaChaEncryptionService.ENVELOPE_PREFIX
    if not s.startswith(prefix):
        return False
    payload = s[len(prefix):]
    if len(payload) < 40 or len(payload) % 4 != 0:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", payload) is not None


@pytest.mark.parametrize(
    ("model", "field", "max_characters"),
    (
        (User, "driver_lic_no", 10),
        (ElectoralRoll, "driver_license_number", 10),
        (ElectoralRoll, "full_name", 255),
        (ElectoralRoll, "address_line1", 255),
        (ElectoralRoll, "address_line2", 255),
        (ElectoralRoll, "suburb", 255),
        (ElectoralRoll, "state", 50),
        (ElectoralRoll, "postcode", 50),
    ),
)
def test_maximum_unicode_pii_envelope_fits_physical_column(
    app,
    model,
    field,
    max_characters,
):
    with app.app_context():
        plaintext = "\U0001f600" * max_characters
        encrypted = ChaChaEncryptionService.get_instance().encrypt(plaintext)
        physical_capacity = model.__table__.c[field].type.length

        assert len(encrypted) <= physical_capacity
        assert ChaChaEncryptionService.get_instance().decrypt(encrypted) == plaintext


def test_pii_encrypted_at_rest(app):
    with app.app_context():
        # Create a fresh enrolment to ensure the TypeDecorator's bind hook runs
        user = User.query.filter_by(username='voter1').first()
        assert user is not None

        # Use the same region as existing data
        from app.models import Region
        region = Region.query.first()
        assert region is not None

        new_enrol = ElectoralRoll(
            roll_number='TEST999',
            driver_license_number='DL999999',
            full_name='Alice Example',
            date_of_birth=user.created_at.date(),
            address_line1='9 Example Rd',
            suburb='Examplestan',
            state='NSW',
            postcode='2999',
            region=region,
            status='active',
            verified=True,
            user=user,
        )
        db.session.add(new_enrol)
        db.session.commit()

        # ORM returns plaintext
        assert new_enrol.full_name == 'Alice Example'

        # Raw storage is encrypted
        row = db.session.execute(
            text("SELECT full_name FROM electoral_roll WHERE id = :id"), {"id": new_enrol.id}
        ).fetchone()
        stored = row[0]
        assert isinstance(stored, str)
        assert stored != 'Alice Example'
        assert is_base64_padded(stored)


def test_admin_can_view_pii(client, app):
    # Login as admin (created in tests/conftest.py)
    resp = client.post("/login", data={"username": "admin", "password": "Admin@123456!"}, follow_redirects=True)
    assert resp.status_code == 200

    # Admin voters page should include decrypted full name
    resp = client.get("/admin/voters", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Test Voter" in resp.data


def test_voter_cannot_view_admin_voters(client, app):
    # Login as regular voter
    resp = client.post("/login", data={"username": "voter1", "password": "Password@123!"}, follow_redirects=True)
    assert resp.status_code == 200

    # Attempt to access admin voters page; should redirect or show access denied without PII
    resp = client.get("/admin/voters", follow_redirects=True)
    assert resp.status_code == 200
    # Should not leak PII on the redirected page
    assert b"Test Voter" not in resp.data


def test_tampered_ciphertext_fails_closed(app):
    with app.app_context():
        service = ChaChaEncryptionService.get_instance()
        encrypted = service.encrypt("Sensitive voter name")
        prefix = service.ENVELOPE_PREFIX
        combined = bytearray(base64.b64decode(encrypted[len(prefix):], validate=True))
        combined[-1] ^= 1
        tampered = prefix + base64.b64encode(combined).decode("ascii")

        with pytest.raises(PIIDecryptionError, match="authenticated decryption"):
            service.decrypt(tampered)


def test_wrong_key_fails_closed_and_original_key_still_decrypts(app):
    original_key = os.environ["VOTER_PII_KEY_BASE64"]
    with app.app_context():
        original_service = ChaChaEncryptionService.initialize(original_key)
        encrypted = original_service.encrypt("DL999999")
        wrong_key = base64.b64encode(b"x" * 32).decode("ascii")
        try:
            wrong_service = ChaChaEncryptionService.initialize(wrong_key)
            with pytest.raises(PIIDecryptionError, match="authenticated decryption"):
                wrong_service.decrypt(encrypted)
        finally:
            restored_service = ChaChaEncryptionService.initialize(original_key)

        assert restored_service.decrypt(encrypted) == "DL999999"


def test_runtime_rejects_unversioned_and_plaintext_values(app):
    with app.app_context():
        service = ChaChaEncryptionService.get_instance()
        for unsafe_value in (
            "legacy plaintext",
            base64.b64encode(os.urandom(40)).decode("ascii"),
            service.LEGACY_PLAINTEXT_PREFIX + "reviewed plaintext",
        ):
            with pytest.raises(PIIDecryptionError, match="version marker"):
                service.decrypt(unsafe_value)


def test_explicit_legacy_migration_paths_produce_current_envelopes(app):
    with app.app_context():
        service = ChaChaEncryptionService.get_instance()

        with pytest.raises(LegacyPIIMigrationError, match="explicit"):
            service.migrate_legacy_plaintext("unmarked plaintext")
        migrated_plaintext = service.migrate_legacy_plaintext(
            service.LEGACY_PLAINTEXT_PREFIX + "Marked legacy voter"
        )
        assert service.decrypt(migrated_plaintext) == "Marked legacy voter"

        legacy_nonce = os.urandom(service.NONCE_BYTES)
        legacy_combined = legacy_nonce + service.cipher.encrypt(
            legacy_nonce,
            b"Old ChaCha voter",
            None,
        )
        legacy_ciphertext = base64.b64encode(legacy_combined).decode("ascii")
        with pytest.raises(PIIDecryptionError, match="version marker"):
            service.decrypt(legacy_ciphertext)
        migrated_ciphertext = service.migrate_legacy_ciphertext(legacy_ciphertext)
        assert service.decrypt(migrated_ciphertext) == "Old ChaCha voter"


def test_explicit_legacy_fernet_conversion_requires_the_matching_key(
    app,
    monkeypatch,
):
    from scripts import migrate_pii_envelope

    key = Fernet.generate_key()
    legacy_value = Fernet(key).encrypt(b"Old Fernet voter").decode("ascii")
    monkeypatch.setenv("OLD_FERNET_KEY", key.decode("ascii"))

    with app.app_context():
        service = ChaChaEncryptionService.get_instance()
        fernet = migrate_pii_envelope._legacy_fernet("legacy-fernet")
        migrated, changed = migrate_pii_envelope._convert(
            service,
            legacy_value,
            "legacy-fernet",
            fernet,
        )
        assert changed is True
        assert service.decrypt(migrated) == "Old Fernet voter"

        monkeypatch.setenv(
            "OLD_FERNET_KEY",
            Fernet.generate_key().decode("ascii"),
        )
        wrong_fernet = migrate_pii_envelope._legacy_fernet("legacy-fernet")
        with pytest.raises(RuntimeError, match="failed decryption"):
            migrate_pii_envelope._convert(
                service,
                legacy_value,
                "legacy-fernet",
                wrong_fernet,
            )


def test_encrypted_type_does_not_return_tampered_database_value(app):
    with app.app_context():
        enrolment = ElectoralRoll.query.filter_by(roll_number="TEST001").one()
        enrolment_id = enrolment.id
        raw = db.session.execute(
            text("SELECT full_name FROM electoral_roll WHERE id = :id"),
            {"id": enrolment_id},
        ).scalar_one()
        prefix = ChaChaEncryptionService.ENVELOPE_PREFIX
        combined = bytearray(base64.b64decode(raw[len(prefix):], validate=True))
        combined[-1] ^= 1
        tampered = prefix + base64.b64encode(combined).decode("ascii")
        db.session.execute(
            text("UPDATE electoral_roll SET full_name = :value WHERE id = :id"),
            {"value": tampered, "id": enrolment_id},
        )
        db.session.commit()
        db.session.expire_all()

        with pytest.raises(PIIDecryptionError, match="authenticated decryption"):
            db.session.get(ElectoralRoll, enrolment_id)

        stored_after_failure = db.session.execute(
            text("SELECT full_name FROM electoral_roll WHERE id = :id"),
            {"id": enrolment_id},
        ).scalar_one()
        assert stored_after_failure == tampered


def test_unrelated_user_update_does_not_rehash_or_reencrypt_licence(
    app,
    monkeypatch,
):
    with app.app_context():
        user = User.query.filter_by(username="voter1").one()
        user_id = user.id
        original_hash = user.driver_lic_hash
        original_ciphertext = db.session.execute(
            text('SELECT driver_lic_no FROM "user" WHERE id = :id'),
            {"id": user_id},
        ).scalar_one()

        def unexpected_hash(_value):
            raise AssertionError("licence blind index was recomputed")

        monkeypatch.setattr(models, "_hash_lic", unexpected_hash)
        user.email = "voter1-updated@example.test"
        db.session.commit()

        stored_hash, stored_ciphertext = db.session.execute(
            text('SELECT driver_lic_hash, driver_lic_no FROM "user" WHERE id = :id'),
            {"id": user_id},
        ).one()
        assert stored_hash == original_hash
        assert stored_ciphertext == original_ciphertext


def test_explicit_migration_updates_both_blind_indexes_atomically_and_dry_run(
    app,
    monkeypatch,
):
    from scripts import migrate_pii_envelope

    def legacy_ciphertext(service, plaintext):
        nonce = os.urandom(service.NONCE_BYTES)
        combined = nonce + service.cipher.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            None,
        )
        return base64.b64encode(combined).decode("ascii")

    with app.app_context():
        service = ChaChaEncryptionService.get_instance()
        user = User.query.filter_by(username="voter1").one()
        enrolment = ElectoralRoll.query.filter_by(roll_number="TEST001").one()
        user_id = user.id
        enrolment_id = enrolment.id
        user_legacy = legacy_ciphertext(service, "VIC00014")
        roll_legacy = legacy_ciphertext(service, "DL123456")
        db.session.execute(
            text(
                'UPDATE "user" SET driver_lic_no = :value, '
                'driver_lic_hash = :hash WHERE id = :id'
            ),
            {"value": user_legacy, "hash": "stale-user-hash", "id": user_id},
        )
        db.session.execute(
            text(
                "UPDATE electoral_roll SET driver_license_number = :value, "
                "driver_license_hash = :hash WHERE id = :id"
            ),
            {"value": "not-valid-ciphertext", "hash": "stale-roll-hash", "id": enrolment_id},
        )
        db.session.commit()

    monkeypatch.setattr(migrate_pii_envelope, "create_app", lambda: app)

    # The user update is staged before the bad electoral-roll value is found.
    # One transaction must roll both back.
    with pytest.raises(RuntimeError, match="no changes were committed"):
        migrate_pii_envelope.migrate("legacy-chacha", True)
    with app.app_context():
        assert db.session.execute(
            text('SELECT driver_lic_no, driver_lic_hash FROM "user" WHERE id = :id'),
            {"id": user_id},
        ).one() == (user_legacy, "stale-user-hash")

        db.session.execute(
            text(
                "UPDATE electoral_roll SET driver_license_number = :value "
                "WHERE id = :id"
            ),
            {"value": roll_legacy, "id": enrolment_id},
        )
        db.session.commit()

    assert migrate_pii_envelope.migrate("legacy-chacha", False) == 2
    with app.app_context():
        assert db.session.execute(
            text('SELECT driver_lic_no, driver_lic_hash FROM "user" WHERE id = :id'),
            {"id": user_id},
        ).one() == (user_legacy, "stale-user-hash")
        assert db.session.execute(
            text(
                "SELECT driver_license_number, driver_license_hash "
                "FROM electoral_roll WHERE id = :id"
            ),
            {"id": enrolment_id},
        ).one() == (roll_legacy, "stale-roll-hash")

    assert migrate_pii_envelope.migrate("legacy-chacha", True) == 2
    with app.app_context():
        user_value, user_hash = db.session.execute(
            text('SELECT driver_lic_no, driver_lic_hash FROM "user" WHERE id = :id'),
            {"id": user_id},
        ).one()
        roll_value, roll_hash = db.session.execute(
            text(
                "SELECT driver_license_number, driver_license_hash "
                "FROM electoral_roll WHERE id = :id"
            ),
            {"id": enrolment_id},
        ).one()
        assert user_value.startswith(ChaChaEncryptionService.ENVELOPE_PREFIX)
        assert roll_value.startswith(ChaChaEncryptionService.ENVELOPE_PREFIX)
        assert user_hash == models._hash_lic("VIC00014")
        assert roll_hash == models._hash_lic("DL123456")


@pytest.mark.parametrize("apply_changes", (False, True))
def test_migration_rejects_insufficient_reflected_capacity_before_writes(
    app,
    monkeypatch,
    apply_changes,
):
    from scripts import migrate_pii_envelope

    with app.app_context():
        service = ChaChaEncryptionService.get_instance()
        enrolment = ElectoralRoll.query.filter_by(roll_number="TEST001").one()
        enrolment_id = enrolment.id
        current = db.session.execute(
            text("SELECT full_name FROM electoral_roll WHERE id = :id"),
            {"id": enrolment_id},
        ).scalar_one()
        plaintext = service.decrypt(current)
        nonce = os.urandom(service.NONCE_BYTES)
        legacy = base64.b64encode(
            nonce + service.cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
        ).decode("ascii")
        db.session.execute(
            text("UPDATE electoral_roll SET full_name = :value WHERE id = :id"),
            {"value": legacy, "id": enrolment_id},
        )
        db.session.commit()

    monkeypatch.setattr(migrate_pii_envelope, "create_app", lambda: app)
    monkeypatch.setitem(
        migrate_pii_envelope.MIN_ENCRYPTED_COLUMN_LENGTHS,
        ("electoral_roll", "full_name"),
        9999,
    )

    with pytest.raises(RuntimeError, match="refused before writes"):
        migrate_pii_envelope.migrate("legacy-chacha", apply_changes)

    with app.app_context():
        stored = db.session.execute(
            text("SELECT full_name FROM electoral_roll WHERE id = :id"),
            {"id": enrolment_id},
        ).scalar_one()
        assert stored == legacy


@pytest.mark.parametrize("apply_changes", (False, True))
def test_migration_rejects_overlength_envelope_before_writes(
    app,
    monkeypatch,
    apply_changes,
):
    from scripts import migrate_pii_envelope

    with app.app_context():
        enrolment = ElectoralRoll.query.filter_by(roll_number="TEST001").one()
        enrolment_id = enrolment.id
        marked_plaintext = (
            ChaChaEncryptionService.LEGACY_PLAINTEXT_PREFIX + "A" * 2000
        )
        db.session.execute(
            text("UPDATE electoral_roll SET full_name = :value WHERE id = :id"),
            {"value": marked_plaintext, "id": enrolment_id},
        )
        db.session.commit()

    monkeypatch.setattr(migrate_pii_envelope, "create_app", lambda: app)

    with pytest.raises(RuntimeError, match="no changes were committed") as error:
        migrate_pii_envelope.migrate("marked-plaintext", apply_changes)
    assert "exceeds reflected capacity" in str(error.value.__cause__)

    with app.app_context():
        stored = db.session.execute(
            text("SELECT full_name FROM electoral_roll WHERE id = :id"),
            {"id": enrolment_id},
        ).scalar_one()
        assert stored == marked_plaintext
