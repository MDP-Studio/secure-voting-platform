from pathlib import Path
from flask import current_app
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature
from .vault_client import vault_client

# --- KEY STORAGE ---
# We will load the keys into these global variables the first time they are needed.
_private_key = None
_public_key = None

def load_keys():
    """
    Loads keys from the Flask instance folder. This function is called automatically
    when signing or verifying for the first time.
    """
    global _private_key, _public_key

    # Use Flask's standard way of finding the instance folder.
    # This correctly resolves to /app/instance inside Docker.
    instance_path = Path(current_app.instance_path)
    private_key_path = instance_path / "private_key.pem"
    public_key_path = instance_path / "public_key.pem"

    try:
        with open(private_key_path, "rb") as key_file:
            _private_key = serialization.load_pem_private_key(key_file.read(), password=None)

        with open(public_key_path, "rb") as key_file:
            _public_key = serialization.load_pem_public_key(key_file.read())
    except FileNotFoundError as e:
        # This will give a much clearer error in the logs if files are missing.
        current_app.logger.error(f"FATAL: Could not load key files: {e}")
        _private_key = None
        _public_key = None


def sign_data(data: bytes) -> bytes:
    """Signs the given data using Vault Transit if configured, otherwise local RSA key."""
    # Prefer Vault Transit if available
    key_name = current_app.config.get('VAULT_TRANSIT_KEY', 'results-signing')
    sig = vault_client.transit_sign(key_name, data)
    if sig:
        return sig

    if _private_key is None:
        load_keys()  # Attempt to load the keys on first use.

    if not _private_key:
        raise RuntimeError("Private key is not loaded. Check application logs for errors.")
        
    signature = _private_key.sign(
        data,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature

def verify_signature(data: bytes, signature: bytes) -> bool:
    """Verifies a signature using Vault Transit if configured, otherwise local RSA public key."""
    key_name = current_app.config.get('VAULT_TRANSIT_KEY', 'results-signing')
    if vault_client.is_enabled:
        try:
            return vault_client.transit_verify(key_name, data, signature)
        except Exception:
            pass
    if _public_key is None:
        load_keys()  # Attempt to load the keys on first use.

    if not _public_key:
        raise RuntimeError("Public key is not loaded. Check application logs for errors.")

    try:
        _public_key.verify(
            signature,
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except InvalidSignature:
        return False