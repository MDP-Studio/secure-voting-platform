from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization

# 1. Define the path to the instance folder relative to this script.
# This ensures it's always created in the project root.
INSTANCE_FOLDER = Path(__file__).parent / "instance"

# 2. Create the instance folder if it doesn't already exist.
INSTANCE_FOLDER.mkdir(exist_ok=True)
print(f"✅ Ensured instance folder exists at: {INSTANCE_FOLDER.resolve()}")

# 3. Generate a new private key
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=4096,
)

# 4. Derive the public key from the private key
public_key = private_key.public_key()

# 5. Save the private key to the correct location (inside the instance folder)
private_key_path = INSTANCE_FOLDER / "private_key.pem"
with open(private_key_path, "wb") as f:
    f.write(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ))
print(f"✅ Private key saved to {private_key_path.name}")

# 6. Save the public key to the correct location
public_key_path = INSTANCE_FOLDER / "public_key.pem"
with open(public_key_path, "wb") as f:
    f.write(public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ))
print(f"✅ Public key saved to {public_key_path.name}")
print("✅ Key pair generation complete.")