"""
auth: admin password hashing, shared by the setup flow and the settings page.

Each install generates its own random salt (stored in config.json as
"admin_password_salt") rather than a single hardcoded salt shared by every
OfflineHub install. A hardcoded salt only stops generic rainbow tables; it
does nothing once the salt itself is public (this repo is), since one
rainbow table built against that one known salt then works against every
installation of the app.
"""

import hashlib
import secrets

_ITERATIONS = 200_000


def generate_salt() -> str:
    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    if not stored_hash or not salt:
        return False
    return hash_password(password, salt) == stored_hash
