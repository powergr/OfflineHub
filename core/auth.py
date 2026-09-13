"""
auth — admin password hashing, shared by the setup flow and the settings page.
"""

import hashlib

_ITERATIONS = 200_000
_SALT = b"hubsalt"


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), _SALT, _ITERATIONS).hex()


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    return hash_password(password) == stored_hash
