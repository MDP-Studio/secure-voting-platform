#!/bin/sh

# Configure the local-development Vault and hand the web process only a scoped
# token. Root credentials remain in this one-shot initializer.
set -eu

: "${VAULT_ADDR:?VAULT_ADDR is required}"
: "${VAULT_TOKEN:?VAULT_TOKEN is required for one-shot initialization}"
: "${VAULT_MOUNT:?VAULT_MOUNT is required}"
: "${VAULT_KV_MOUNT:?VAULT_KV_MOUNT is required}"
: "${VAULT_TRANSIT_KEY:?VAULT_TRANSIT_KEY is required}"
: "${VAULT_TOKEN_OUTPUT:?VAULT_TOKEN_OUTPUT is required}"

case "${VAULT_TOKEN}" in
    CHANGE_ME*|change_me*|REPLACE_*|replace_*)
        echo "VAULT_TOKEN must not be a placeholder" >&2
        exit 1
        ;;
esac
if [ "${#VAULT_TOKEN}" -lt 16 ]; then
    echo "VAULT_TOKEN must be at least 16 characters" >&2
    exit 1
fi

until vault status >/dev/null 2>&1; do
    sleep 2
done

if ! vault secrets list -format=json | grep -q "\"${VAULT_MOUNT}/\""; then
    vault secrets enable -path="${VAULT_MOUNT}" transit >/dev/null
fi

if ! vault read "${VAULT_MOUNT}/keys/${VAULT_TRANSIT_KEY}" >/dev/null 2>&1; then
    vault write -f "${VAULT_MOUNT}/keys/${VAULT_TRANSIT_KEY}" \
        type=rsa-2048 >/dev/null
fi

if ! vault secrets list -format=json | grep -q "\"${VAULT_KV_MOUNT}/\""; then
    vault secrets enable -path="${VAULT_KV_MOUNT}" kv-v2 >/dev/null
fi

vault policy write securevote-web - >/dev/null <<EOF
path "${VAULT_MOUNT}/sign/${VAULT_TRANSIT_KEY}" {
  capabilities = ["update"]
}

path "${VAULT_MOUNT}/verify/${VAULT_TRANSIT_KEY}" {
  capabilities = ["update"]
}

path "${VAULT_MOUNT}/keys/${VAULT_TRANSIT_KEY}" {
  capabilities = ["read"]
}
EOF

umask 077
mkdir -p "$(dirname "${VAULT_TOKEN_OUTPUT}")"
vault token create \
    -field=token \
    -policy=securevote-web \
    -ttl=168h \
    -renewable=true >"${VAULT_TOKEN_OUTPUT}"

test -s "${VAULT_TOKEN_OUTPUT}"
echo "Vault Transit and scoped web credentials are ready."
