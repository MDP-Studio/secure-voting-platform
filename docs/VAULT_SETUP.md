# Vault Transit setup

SecureVote can sign closed-election result packages with HashiCorp Vault
Transit. Each persisted signature records the Vault cluster, namespace, mount,
key name, key version, algorithm, and complete signature envelope. Verification
uses that stored provenance and never falls back to a local key when Vault was
the signer.

## Required identity

Vault-backed signing requires all of the following:

```text
VAULT_ADDR
VAULT_CLUSTER_ID
VAULT_MOUNT
VAULT_TRANSIT_KEY
VAULT_TOKEN or VAULT_TOKEN_FILE
```

`VAULT_CLUSTER_ID` is a stable, non-secret identifier for the Vault deployment.
It must remain unchanged for the lifetime of signatures produced by that
cluster. Set `VAULT_NAMESPACE` when using Vault Enterprise namespaces.

The application token needs only these capabilities for its configured key:

```hcl
path "transit/sign/results-signing" {
  capabilities = ["update"]
}

path "transit/verify/results-signing" {
  capabilities = ["update"]
}

path "transit/keys/results-signing" {
  capabilities = ["read"]
}
```

Do not give the web process a Vault root token.

## Local Compose workflow

Copy `.env.example` to `.env` and fill every blank required secret. In
particular, generate a random `VAULT_DEV_ROOT_TOKEN` of at least 16 characters;
it is used only by the local dev Vault and the one-shot initializer.

```bash
docker compose up --build -d
docker compose ps
docker compose logs vault-init
```

The local stack performs this sequence:

1. `vault` starts in development mode on the internal application network.
2. `vault-init` enables the configured Transit mount, creates the RSA signing
   key and least-privilege policy, and writes a scoped token to a named volume.
3. `web` mounts that token file read-only at `/run/vault/token`.

Vault has no host port mapping in this profile. Inspect it from inside its
container when debugging:

```bash
docker compose exec vault vault status
docker compose exec vault vault secrets list
```

Run the application-level checks inside the web container so they use its
internal Vault address and read-only scoped token file:

```bash
docker compose exec web python scripts/vault_integration_check.py
docker compose exec web python scripts/demo_vault_signing.py
```

The generated web token has a seven-day development TTL. Recreate the
`vault-init` service before it expires:

```bash
docker compose up --force-recreate vault-init
docker compose restart web
```

This workflow is for local infrastructure verification. It is not a production
Vault deployment.

## External Vault

For a real deployment:

1. Use an initialized, unsealed, TLS-protected Vault cluster outside this
   Compose file.
2. Enable Transit and create a dedicated asymmetric signing key.
3. Issue a renewable workload identity with only the policy above. Prefer an
   orchestrator-managed secret file and set `VAULT_TOKEN_FILE`.
4. Set a stable `VAULT_CLUSTER_ID` and the exact namespace, mount, and key name.
5. Remove the local `vault` and `vault-init` services from the deployment.
6. Monitor token renewal, key rotation, audit-device health, and Vault
   availability.

Example environment:

```text
VAULT_ADDR=https://vault.example.internal
VAULT_TOKEN_FILE=/run/secrets/securevote-vault-token
VAULT_CLUSTER_ID=au-prod-vault-01
VAULT_NAMESPACE=elections
VAULT_MOUNT=transit
VAULT_TRANSIT_KEY=results-signing
```

## Rotation and verification

Vault Transit signatures contain their key version. SecureVote preserves the
complete `vault:vN:...` envelope and submits it unchanged during verification.
Do not trim the version prefix or re-encode the signature.

Local RSA fallback keys are different: their public keys are archived in
`result_signing_public_key` with a SHA-256 fingerprint. Historical verification
uses that immutable database archive, not the current runtime key file.

If Vault is configured but unavailable, result signing and Vault-backed
verification fail closed. Diagnose the token source, cluster identity, Transit
mount, key name, and network path rather than switching an existing result to a
different backend.
