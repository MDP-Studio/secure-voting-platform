#!/usr/bin/env bash
set -euo pipefail

# Provision HashiCorp Vault for this app:
# - Enable/ensure transit and kv v2 mounts
# - Create transit key for result signing
# - Write JWT secret in KV v2

VAULT_ADDR=${VAULT_ADDR:-}
VAULT_TOKEN=${VAULT_TOKEN:-}
TRANSIT_MOUNT=${VAULT_MOUNT:-transit}
KV_MOUNT=${VAULT_KV_MOUNT:-kv}
TRANSIT_KEY=${VAULT_TRANSIT_KEY:-results-signing}
JWT_PATH=${VAULT_JWT_PATH:-app/jwt}
JWT_KEY=${VAULT_JWT_KEY:-secret}
JWT_SECRET_VALUE=${JWT_SECRET_VALUE:-change-me-in-prod}

if [[ -z "$VAULT_ADDR" || -z "$VAULT_TOKEN" ]]; then
  echo "ERROR: VAULT_ADDR and VAULT_TOKEN must be set in the environment" >&2
  exit 1
fi

hdr=("X-Vault-Token: ${VAULT_TOKEN}")

echo "Ensuring transit mount '${TRANSIT_MOUNT}' exists..."
if ! curl -fsS -H "${hdr[@]}" -X GET "${VAULT_ADDR}/v1/sys/mounts/${TRANSIT_MOUNT}/" >/dev/null; then
  curl -fsS -H "${hdr[@]}" -X POST "${VAULT_ADDR}/v1/sys/mounts/${TRANSIT_MOUNT}" \
    -d '{"type":"transit"}'
fi

echo "Ensuring kv v2 mount '${KV_MOUNT}' exists..."
if ! curl -fsS -H "${hdr[@]}" -X GET "${VAULT_ADDR}/v1/sys/mounts/${KV_MOUNT}/" >/dev/null; then
  curl -fsS -H "${hdr[@]}" -X POST "${VAULT_ADDR}/v1/sys/mounts/${KV_MOUNT}" \
    -d '{"type":"kv","options":{"version":"2"}}'
fi

echo "Creating transit key '${TRANSIT_KEY}' (if not exists)..."
curl -fsS -H "${hdr[@]}" -X POST "${VAULT_ADDR}/v1/${TRANSIT_MOUNT}/keys/${TRANSIT_KEY}" \
  -d '{"type":"rsa-2048","exportable":false}' || true

echo "Writing JWT secret at '${KV_MOUNT}/data/${JWT_PATH}' key '${JWT_KEY}'..."
curl -fsS -H "${hdr[@]}" -H 'Content-Type: application/json' \
  -X POST "${VAULT_ADDR}/v1/${KV_MOUNT}/data/${JWT_PATH}" \
  -d "{\"data\":{\"${JWT_KEY}\":\"${JWT_SECRET_VALUE}\"}}"

cat <<POLICY

Suggested Vault policy (attach to the app token):

path "${TRANSIT_MOUNT}/sign/${TRANSIT_KEY}" {
  capabilities = ["update"]
}

path "${TRANSIT_MOUNT}/verify/${TRANSIT_KEY}" {
  capabilities = ["update"]
}

path "${KV_MOUNT}/data/${JWT_PATH}" {
  capabilities = ["read"]
}

POLICY

echo "Done."


