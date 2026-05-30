import logging
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from base64 import b64encode, b64decode
import os
from sqlalchemy.types import TypeDecorator, String
from flask import current_app
import re

class ChaChaEncryptionService:
    _instance = None
    _key = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls, key=None):
        """Initialize encryption service with a key."""
        if key is None:
            # Get key from environment
            key = os.environ.get('VOTER_PII_KEY_BASE64')
            if not key:
                raise RuntimeError("VOTER_PII_KEY_BASE64 environment variable not set")
        
        if isinstance(key, str):
            # Decode base64 key
            try:
                key = b64decode(key)
            except Exception as e:
                raise RuntimeError(f"Invalid base64 key: {e}")
            
        if len(key) != 32:
            raise RuntimeError("ChaCha20Poly1305 requires a 32-byte key")
        
        cls._key = key
        cls._instance = cls()
        return cls._instance

    def __init__(self):
        if self._key is None:
            raise RuntimeError("ChaChaEncryptionService not initialized. Call initialize() first.")
        self.cipher = ChaCha20Poly1305(self._key)

    def encrypt(self, data: str) -> str:
        """Encrypt a string value."""
        if data is None:
            return None
            
        try:
            # Validate and convert input data
            if not isinstance(data, str):
                data = str(data)
            data_bytes = data.encode('utf-8')
            
            # Generate a random 12-byte nonce
            nonce = os.urandom(12)
            
            # Encrypt the data
            ciphertext = self.cipher.encrypt(nonce, data_bytes, None)
            
            # Combine nonce and ciphertext
            combined = nonce + ciphertext
            
            # Perform base64 encoding and ensure proper padding
            encoded = b64encode(combined).decode('ascii')
            padding_needed = (4 - len(encoded) % 4) % 4  # Correct padding calculation
            if padding_needed:
                encoded += '=' * padding_needed
                
            # Validate final output
            if len(encoded) % 4 != 0:
                raise ValueError("Base64 encoding resulted in invalid padding")
                
            return encoded
            
        except Exception as e:
            current_app.logger.error(f"Encryption error: {str(e)}")
            raise RuntimeError(f"Failed to encrypt data: {str(e)}")

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt an encrypted string value."""
        if encrypted_data is None:
            return None

        try:
            # Validate input and remove whitespace
            if not isinstance(encrypted_data, str):
                # Gracefully handle unexpected types by stringifying
                encrypted_data = str(encrypted_data)
            
            s = encrypted_data.strip()

            # Fast path: clearly too short to be a valid ChaCha20-Poly1305 payload
            # Minimum possible: 12-byte nonce + 16-byte tag = 28 bytes -> base64 ~38 chars
            if len(s) < 38:
                # Assume legacy plaintext stored before migration
                return s

            # Strict Base64 validation: only valid chars, proper padding (0,1,2 '=' at end), length % 4 == 0
            base64_re = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
            if (len(s) % 4 != 0) or (not base64_re.match(s)):
                # Not a valid base64 string — treat as plaintext (legacy value)
                return s

            # Decode from base64 with strict validation
            try:
                combined = b64decode(s, validate=True)
            except Exception:
                # Not valid base64 — treat as plaintext
                logging.getLogger(__name__).debug("Handled exception in app/security/encryption.py", exc_info=True)
                return s

            # Validate combined data length (must include 12-byte nonce and at least 16-byte tag)
            if len(combined) < 28:
                # Invalid encrypted blob — treat as plaintext
                return s
            
            # Validate combined data length
            # (The previous check ensures at least 28 bytes, so this is just a defensive check)
            if len(combined) < 12:
                return s
            
            # Extract nonce and ciphertext
            nonce = combined[:12]
            ciphertext = combined[12:]
            
            # Validate nonce length
            if len(nonce) != 12:
                return s
            
            # Decrypt the data
            try:
                plaintext = self.cipher.decrypt(nonce, ciphertext, None)
                return plaintext.decode('utf-8')
            except Exception as e:
                # If decryption fails, fall back to returning the original string (likely plaintext)
                logging.getLogger(__name__).debug("Handled exception in app/security/encryption.py", exc_info=True)
                return s
                
        except Exception as e:
            # Be quiet on decryption path to avoid log spam; return original
            logging.getLogger(__name__).debug("Handled exception in app/security/encryption.py", exc_info=True)
            try:
                return encrypted_data if encrypted_data is not None else None
            except Exception:
                logging.getLogger(__name__).debug("Handled exception in app/security/encryption.py", exc_info=True)
                return None

class EncryptedType(TypeDecorator):
    """SQLAlchemy type for encrypted fields."""
    impl = String
    cache_ok = True
    
    def __init__(self, length=None):
        super().__init__(length=length)
        # Defer service acquisition until first use to avoid initialization order issues
        self.service = None
        self.length = length
        
        # Minimum length needed for encrypted data:
        # 12 bytes nonce + 16 bytes tag + 1 byte data = 29 bytes
        # Base64 encoding: ceil(29 * 4/3) = 40 chars
        self.min_length = 40
        
        # Validate column length
        if length is not None and length < self.min_length:
            raise ValueError(f"Column length must be at least {self.min_length} characters")

    def process_bind_param(self, value, dialect):
        """Encrypt value before saving to DB."""
        if value is None:
            return None
            
        try:
            # Ensure encryption service is initialized
            if self.service is None:
                try:
                    self.service = ChaChaEncryptionService.get_instance()
                except Exception:
                    # Attempt lazy initialization from environment
                    key_b64 = os.environ.get('VOTER_PII_KEY_BASE64')
                    if key_b64:
                        ChaChaEncryptionService.initialize(key_b64)
                        self.service = ChaChaEncryptionService.get_instance()
                    else:
                        raise
            # Convert value to string if needed
            if not isinstance(value, str):
                value = str(value)
                
            # Encrypt the value
            encrypted = self.service.encrypt(value)
            if encrypted is None:
                current_app.logger.error("Encryption returned None")
                raise ValueError("Encryption failed")
                
            # Validate length if specified
            if self.length and len(encrypted) > self.length:
                current_app.logger.error(f"Encrypted value exceeds max length: {len(encrypted)} > {self.length}")
                raise ValueError(f"Encrypted value length ({len(encrypted)}) exceeds column length ({self.length})")
                
            return encrypted
            
        except Exception as e:
            current_app.logger.error(f"Failed to encrypt value: {str(e)}")
            raise

    def process_result_value(self, value, dialect):
        """Decrypt value when loading from DB."""
        if value is None:
            return None
            
        try:
            # Ensure encryption service is initialized
            if self.service is None:
                try:
                    self.service = ChaChaEncryptionService.get_instance()
                except Exception:
                    logging.getLogger(__name__).debug("Handled exception in app/security/encryption.py", exc_info=True)
                    key_b64 = os.environ.get('VOTER_PII_KEY_BASE64')
                    if key_b64:
                        ChaChaEncryptionService.initialize(key_b64)
                        self.service = ChaChaEncryptionService.get_instance()
                    else:
                        # If no key available, return original value (plaintext path)
                        return value
            # Validate input
            if not isinstance(value, str):
                value = str(value)
            
            # If value is clearly too short to be valid ciphertext, treat as plaintext (legacy)
            if len(value) < self.min_length:
                return value
                
            # Attempt decryption
            decrypted = self.service.decrypt(value)
            return decrypted
            
        except Exception as e:
            # Return original value on any unexpected error to keep app functional
            logging.getLogger(__name__).debug("Handled exception in app/security/encryption.py", exc_info=True)
            return value
