import base64
import os
import json
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional

class SecretManagerV2:
    """
    Enterprise-grade secret management with encryption at rest and rotation support.
    """
    def __init__(self, master_key: str, salt: bytes = b'sellmate_v2_prod_salt'):
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
        # Prefix with version for future rotation support
        encrypted_data = self.fernet.encrypt(plaintext.encode()).decode()
        return f"v1:{encrypted_data}"

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        
        if ciphertext.startswith("v1:"):
            actual_ciphertext = ciphertext[3:]
            return self.fernet.decrypt(actual_ciphertext.encode()).decode()
        
        # Fallback for legacy plaintext or during migration
        return ciphertext

    def encrypt_merchant_config(self, config: dict) -> str:
        """Encrypt entire merchant config JSON."""
        return self.encrypt(json.dumps(config))

    def decrypt_merchant_config(self, encrypted_config: str) -> dict:
        """Decrypt merchant config JSON."""
        decrypted = self.decrypt(encrypted_config)
        return json.loads(decrypted) if decrypted else {}

# Singleton instance for the app
# secret_manager = SecretManagerV2(os.getenv("MASTER_KEY"))
