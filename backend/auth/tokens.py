"""
Signed access tokens.

Short-lived and stateless: there is no session table and no revocation
list, so the expiry is the only thing that ends a session. Kept to hours
rather than days for that reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from backend.auth.roles import Role
from backend.config import settings


ALGORITHM = "HS256"


class InvalidToken(Exception):
    """Signature, expiry, shape or role did not check out."""


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    role: Role


def create_access_token(
    *,
    subject: str,
    role: str | Role,
    expires_in: timedelta | None = None,
) -> str:
    lifetime = (
        expires_in
        if expires_in is not None
        else timedelta(hours=settings.JWT_EXPIRE_HOURS)
    )

    return jwt.encode(
        {
            "sub": subject,
            "role": Role(role).value,
            "exp": datetime.now(timezone.utc) + lifetime,
        },
        settings.JWT_SECRET,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> TokenClaims:
    """
    Verify a token and return its claims.

    Every failure raises the same InvalidToken: the caller must not be able
    to tell an expired token from a forged one from a malformed one.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc

    subject = payload.get("sub")
    raw_role = payload.get("role")

    if not subject or not raw_role:
        raise InvalidToken("Token is missing sub or role.")

    try:
        # A valid signature is not enough. A token naming a role this
        # system no longer grants must not be honoured.
        role = Role(raw_role)
    except ValueError as exc:
        raise InvalidToken(f"Unknown role {raw_role!r}.") from exc

    return TokenClaims(subject=subject, role=role)
