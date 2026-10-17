"""
Encryption at rest for secrets stored in the database (AI provider keys).

Fernet (AES-128-CBC + HMAC) with a key derived from KEY_ENCRYPTION_SECRET, or
JWT_SECRET_KEY when that is unset. A database leak or a stray SELECT therefore
does not expose usable provider keys; the server secret is also needed.

Values are stored as "enc:v1:<token>". A value without that prefix is treated
as plaintext so a key pasted straight into the table still works; the next
update through the API re-saves it encrypted.
"""

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    secret = settings.KEY_ENCRYPTION_SECRET.strip() or settings.JWT_SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    return _PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(stored: str) -> Optional[str]:
    """The plaintext, or None if it cannot be decrypted (e.g. secret rotated)."""
    if not stored.startswith(_PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return None


def mask_secret(value: str) -> str:
    """'sk-proj-abcdef...' -> 'sk-****...****'. Never reveals the tail."""
    if len(value) < 12:
        return "****"
    return f"{value[:3]}****...****"
