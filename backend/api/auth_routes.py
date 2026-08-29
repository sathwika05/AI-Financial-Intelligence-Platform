"""
Sign in, and report who is signed in.

There is no registration endpoint. Accounts are created by an operator
running scripts/create_user.py, because this deployment has a handful of
users and a public signup on a system that spends provider credit per
query is a cost hole, not a feature.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.auth.passwords import verify_password
from backend.auth.roles import Role
from backend.auth.tokens import TokenClaims, create_access_token
from backend.models.db_models import User
from backend.services.postgres_service import get_db


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    role: str


class MeResponse(BaseModel):
    email: str
    role: str


# One message for every failure below. Distinguishing "no such account"
# from "wrong password" turns the login into an account-enumeration oracle.
_REFUSED = "Email or password is incorrect."


async def _authenticate(
    *,
    email: str,
    password: str,
    session: AsyncSession,
) -> str:
    """
    Check credentials and mint a token, or raise 401.

    Split from the route so the decision is testable without a running
    database or an HTTP client.
    """
    normalised = email.strip().lower()

    result = await session.execute(
        select(User).where(User.email == normalised)
    )

    user = result.scalar_one_or_none()

    if user is None:
        # Hash a throwaway password anyway so a missing account does not
        # answer measurably faster than a wrong password.
        verify_password(password, "$2b$12$" + "x" * 53)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_REFUSED,
        )

    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_REFUSED,
        )

    if not user.is_active:
        # Same message: a disabled account is not the caller's business.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_REFUSED,
        )

    logger.info("[AUTH] %s signed in as %s", user.email, user.role)

    return create_access_token(subject=user.email, role=user.role)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> LoginResponse:
    token = await _authenticate(
        email=request.email,
        password=request.password,
        session=session,
    )

    result = await session.execute(
        select(User).where(User.email == request.email.strip().lower())
    )
    user = result.scalar_one_or_none()

    return LoginResponse(
        access_token=token,
        email=user.email,
        role=user.role,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    claims: TokenClaims = Depends(require_role(Role.ANALYST)),
) -> MeResponse:
    """
    Who the bearer token belongs to.

    The dashboard calls this on load to decide which navigation to show,
    and to discover that a stored token has expired.
    """
    return MeResponse(email=claims.subject, role=claims.role.value)
