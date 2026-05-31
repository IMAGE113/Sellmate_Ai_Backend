import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecretManager:
    """
    Handles encryption and decryption of merchant secrets and tokens.
    """
    def __init__(self, master_key: str):
        # In production, the master_key should be loaded from a secure environment variable or KMS
        salt = b'sellmate_production_salt' # In production, use a unique salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        self.fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self.fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except Exception:
            # Fallback for legacy plaintext secrets during migration
            return ciphertext

# Example usage: secret_manager = SecretManager(os.getenv("MASTER_ENCRYPTION_KEY"))
