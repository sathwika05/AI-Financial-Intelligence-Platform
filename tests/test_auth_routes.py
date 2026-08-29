"""
Login, identity, and the dependency that guards a handler by role.

The guards are unit-tested against fakes rather than a live database: the
question here is who gets in and who is refused, and that decision must be
readable without a Postgres container.
"""
import uuid

import pytest
from fastapi import HTTPException

from backend.auth.roles import Role


class TestLogin:
    @pytest.mark.asyncio
    async def test_correct_credentials_return_a_token(self):
        from backend.api.auth_routes import _authenticate
        from backend.auth.passwords import hash_password
        from backend.auth.tokens import decode_access_token

        user = _FakeUser(email="a@b.com", password="hunter2", role="analyst")

        token = await _authenticate(
            email="a@b.com",
            password="hunter2",
            session=_FakeSession(user),
        )

        claims = decode_access_token(token)

        assert claims.subject == "a@b.com"
        assert claims.role is Role.ANALYST

    @pytest.mark.asyncio
    async def test_a_wrong_password_is_refused(self):
        from backend.api.auth_routes import _authenticate

        user = _FakeUser(email="a@b.com", password="hunter2", role="analyst")

        with pytest.raises(HTTPException) as caught:
            await _authenticate(
                email="a@b.com",
                password="wrong",
                session=_FakeSession(user),
            )

        assert caught.value.status_code == 401

    @pytest.mark.asyncio
    async def test_an_unknown_email_is_refused_the_same_way(self):
        """
        Identical status and message to a wrong password: a different
        response would confirm which addresses have accounts.
        """
        from backend.api.auth_routes import _authenticate

        with pytest.raises(HTTPException) as unknown:
            await _authenticate(
                email="nobody@b.com",
                password="hunter2",
                session=_FakeSession(None),
            )

        user = _FakeUser(email="a@b.com", password="hunter2", role="analyst")

        with pytest.raises(HTTPException) as wrong:
            await _authenticate(
                email="a@b.com",
                password="wrong",
                session=_FakeSession(user),
            )

        assert unknown.value.status_code == wrong.value.status_code
        assert unknown.value.detail == wrong.value.detail

    @pytest.mark.asyncio
    async def test_a_disabled_account_cannot_log_in(self):
        from backend.api.auth_routes import _authenticate

        user = _FakeUser(
            email="a@b.com",
            password="hunter2",
            role="admin",
            is_active=False,
        )

        with pytest.raises(HTTPException) as caught:
            await _authenticate(
                email="a@b.com",
                password="hunter2",
                session=_FakeSession(user),
            )

        assert caught.value.status_code == 401


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_an_admin_passes_an_admin_guard(self):
        from backend.auth.dependencies import require_role

        guard = require_role(Role.ADMIN)
        claims = await guard(_bearer("admin@b.com", "admin"))

        assert claims.role is Role.ADMIN

    @pytest.mark.asyncio
    async def test_an_admin_passes_an_analyst_guard(self):
        """Admin outranks analyst; it must not be locked out of the app."""
        from backend.auth.dependencies import require_role

        guard = require_role(Role.ANALYST)
        claims = await guard(_bearer("admin@b.com", "admin"))

        assert claims.role is Role.ADMIN

    @pytest.mark.asyncio
    async def test_an_analyst_is_refused_an_admin_guard(self):
        from backend.auth.dependencies import require_role

        guard = require_role(Role.ADMIN)

        with pytest.raises(HTTPException) as caught:
            await guard(_bearer("analyst@b.com", "analyst"))

        # 403, not 401: they are authenticated, just not permitted.
        assert caught.value.status_code == 403

    @pytest.mark.asyncio
    async def test_a_missing_token_is_401(self):
        from backend.auth.dependencies import require_role

        guard = require_role(Role.ANALYST)

        with pytest.raises(HTTPException) as caught:
            await guard(None)

        assert caught.value.status_code == 401

    @pytest.mark.asyncio
    async def test_a_forged_token_is_401(self):
        from backend.auth.dependencies import require_role

        guard = require_role(Role.ANALYST)

        with pytest.raises(HTTPException) as caught:
            await guard(_raw_bearer("clearly.not.a.token"))

        assert caught.value.status_code == 401


def _bearer(email: str, role: str):
    from fastapi.security import HTTPAuthorizationCredentials

    from backend.auth.tokens import create_access_token

    return HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_access_token(subject=email, role=role),
    )


def _raw_bearer(token: str):
    from fastapi.security import HTTPAuthorizationCredentials

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class _FakeUser:
    def __init__(self, *, email, password, role, is_active=True):
        from backend.auth.passwords import hash_password

        self.id = uuid.uuid4()
        self.email = email
        self.password_hash = hash_password(password)
        self.role = role
        self.is_active = is_active


class _FakeSession:
    def __init__(self, user):
        self._user = user

    async def execute(self, _statement):
        return _FakeResult(self._user)


class _FakeResult:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user
