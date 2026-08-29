"""
Passwords, tokens and roles.

The admin routes had no authentication at all: every handler in
admin_llm_routes took only Depends(get_db), so anyone who could reach the
API could overwrite the stored provider key or delete provider rows. The
deployment gate hid them from preprod; it did not protect production.

Two roles, because the split people actually need is "can change the
system" versus "can use it". An analyst runs benchmarks and asks questions;
an admin also configures providers and re-indexes the corpus.
"""
import pytest


class TestPasswordHashing:
    def test_a_password_verifies_against_its_own_hash(self):
        from backend.auth.passwords import hash_password, verify_password

        hashed = hash_password("correct horse battery staple")

        assert verify_password("correct horse battery staple", hashed)

    def test_a_wrong_password_is_rejected(self):
        from backend.auth.passwords import hash_password, verify_password

        hashed = hash_password("correct horse battery staple")

        assert not verify_password("Correct Horse Battery Staple", hashed)

    def test_the_hash_is_not_the_password(self):
        from backend.auth.passwords import hash_password

        hashed = hash_password("hunter2")

        assert "hunter2" not in hashed

    def test_the_same_password_hashes_differently_each_time(self):
        """Per-hash salt: identical passwords must not share a hash."""
        from backend.auth.passwords import hash_password

        assert hash_password("hunter2") != hash_password("hunter2")

    def test_a_malformed_hash_is_rejected_rather_than_raising(self):
        """
        A truncated or hand-edited hash column must fail the login, not
        500 the endpoint.
        """
        from backend.auth.passwords import verify_password

        assert not verify_password("hunter2", "not-a-bcrypt-hash")


class TestTokens:
    def test_a_token_round_trips_its_subject_and_role(self):
        from backend.auth.tokens import create_access_token, decode_access_token

        token = create_access_token(subject="a@b.com", role="analyst")
        claims = decode_access_token(token)

        assert claims.subject == "a@b.com"
        assert claims.role == "analyst"

    def test_a_token_signed_with_another_secret_is_rejected(self):
        import jwt as pyjwt

        from backend.auth.tokens import decode_access_token, InvalidToken

        forged = pyjwt.encode(
            {"sub": "a@b.com", "role": "admin"},
            "not-the-secret",
            algorithm="HS256",
        )

        with pytest.raises(InvalidToken):
            decode_access_token(forged)

    def test_an_expired_token_is_rejected(self):
        from datetime import timedelta

        from backend.auth.tokens import create_access_token, decode_access_token, InvalidToken

        token = create_access_token(
            subject="a@b.com",
            role="analyst",
            expires_in=timedelta(seconds=-1),
        )

        with pytest.raises(InvalidToken):
            decode_access_token(token)

    def test_garbage_is_rejected(self):
        from backend.auth.tokens import decode_access_token, InvalidToken

        with pytest.raises(InvalidToken):
            decode_access_token("nonsense")

    def test_an_unknown_role_in_a_token_is_rejected(self):
        """
        A valid signature is not enough: the role has to be one this
        system actually grants, or a stale token naming a removed role
        would be honoured.
        """
        import jwt as pyjwt

        from backend.auth.tokens import decode_access_token, InvalidToken
        from backend.config import settings

        token = pyjwt.encode(
            {"sub": "a@b.com", "role": "superuser"},
            settings.JWT_SECRET,
            algorithm="HS256",
        )

        with pytest.raises(InvalidToken):
            decode_access_token(token)


class TestRoles:
    def test_admin_outranks_analyst(self):
        from backend.auth.roles import Role, has_at_least

        assert has_at_least(Role.ADMIN, Role.ANALYST)

    def test_analyst_does_not_reach_admin(self):
        from backend.auth.roles import Role, has_at_least

        assert not has_at_least(Role.ANALYST, Role.ADMIN)

    def test_a_role_satisfies_itself(self):
        from backend.auth.roles import Role, has_at_least

        assert has_at_least(Role.ANALYST, Role.ANALYST)
        assert has_at_least(Role.ADMIN, Role.ADMIN)

    def test_only_two_roles_exist(self):
        """
        The mock showed a third, Viewer. It is not implemented, so it must
        not be silently accepted anywhere.
        """
        from backend.auth.roles import Role

        assert {r.value for r in Role} == {"admin", "analyst"}
