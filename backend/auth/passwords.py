"""
Password hashing.

bcrypt directly rather than passlib: passlib is unmaintained against
bcrypt 4.x and its version-detection shim warns on every import.
"""
from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """Hash with a per-call salt, so identical passwords never collide."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """
    Constant-time check against a stored hash.

    A malformed hash -- truncated, hand-edited, or written by something
    else -- fails the login rather than raising, so a bad row cannot 500
    the endpoint and disclose that the account exists.
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
