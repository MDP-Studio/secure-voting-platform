# Database migrations

SecureVote uses Flask-Migrate/Alembic against the shared election schema. The
admin and voter bindings are separate credentials for that same schema, so run
each migration once through the primary `DATABASE_URL`.

```powershell
python -m flask --app app.wsgi:app db upgrade
```

The migration chain supports both a fresh empty database and the legacy 2025
schema stamped at `20251005_add_uq_vote_user`.

CI applies the legacy fixture to a live MySQL 8.4 service as well as exercising
fresh and populated SQLite migration paths. These migrations are forward-only:
after a successful upgrade, retain the upgraded schema if application code is
rolled back. If MySQL stops after partial DDL, restore the pre-upgrade backup
before correcting the failure and retrying.

The 2026 migration preserves legacy candidates and ballots, removes the
identity-bearing `vote.user_id`, creates election-scoped receipts and anonymous
nullifiers, invalidates legacy nonce-linked blind authorizations, and adds OTP
and durable result-signing tables. SQLite preservation is covered by an
automated migration test, so deleting a development database is not required.

Before removing linkable legacy blind-token rows, the migration records
`blind_key_recovery_required` on every open election when any authorization
history exists. This durable quarantine prevents the absence of migrated token
rows from being misread as proof that no authorization was ever issued.

Before upgrading a populated database:

1. Stop ballot traffic.
2. Back up the database and the `instance/` key directory.
3. Run the migration command.
4. Run `python scripts/anchor_open_election_keys.py`. It validates existing
   anchors and provisions only an unanchored open election with no issued blind
   authorizations.
5. Verify `alembic_version`, database grants, and readiness before traffic.

Never generate a replacement key for an election that already has an anchored
fingerprint. Restore its original instance key directory instead.

If an open election has issued authorizations but no database anchor, the
reconciliation script fails closed. Do not clear
`blind_key_recovery_required` ad hoc and do not generate a replacement key.
Close or cancel the quarantined election, reconcile outstanding voter receipts
through the documented election-operations process, and start a new election
with a freshly generated and anchored authority.
