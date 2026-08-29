"""
FastAPI guards.

require_role(Role.X) returns a dependency that admits anyone whose token
carries X or better, and refuses everyone else. Roles are ranked, so an
admin is never locked out of a handler an analyst can reach.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.roles import Role, has_at_least
from backend.auth.tokens import InvalidToken, TokenClaims, decode_access_token


# auto_error=False so a missing header reaches the guard as None and gets
# the same 401 shape as a bad one, rather than FastAPI's own 403.
bearer_scheme = HTTPBearer(auto_error=False)


def require_role(required: Role):
    async def guard(
        credentials: HTTPAuthorizationCredentials | None = Depends(
            bearer_scheme
        ),
    ) -> TokenClaims:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in to use this endpoint.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            claims = decode_access_token(credentials.credentials)
        except InvalidToken:
            # Deliberately not saying which part failed: expiry, signature
            # and shape all look the same from outside.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session is invalid or has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not has_at_least(claims.role, required):
            # 403 rather than 401: they are who they say, just not
            # permitted, and retrying with the same token will not help.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action needs the {required.value} role; "
                    f"you have {claims.role.value}."
                ),
            )

        return claims

    # Lets the route table be asserted against: a test can read which role
    # a mounted route demands without exercising every handler.
    guard.__required_role__ = required

    return guard
