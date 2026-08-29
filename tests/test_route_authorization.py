"""
Which role each route requires.

The security review found every admin_llm_routes handler taking only
Depends(get_db) -- no authentication at all. DEPLOYMENT_MODE stopped
preprod serving them; it did nothing for a production deployment, where
an unauthenticated caller could still overwrite the stored provider key.

This asserts the guard is actually attached, per route, rather than
trusting that someone remembered.
"""
import pytest

from backend.auth.roles import Role


ADMIN_ONLY = (
    # Configuring providers and re-indexing the corpus change the system
    # and spend money.
    ("POST", "/admin/llm/providers"),
    ("PATCH", "/admin/llm/providers/{provider_id}"),
    ("DELETE", "/admin/llm/providers/{provider_id}"),
    ("POST", "/admin/llm/providers/{provider_id}/set-default"),
    ("POST", "/api/index/documents"),
    # Reading the provider list too: only the launcher needs it, and the
    # launcher is an admin screen.
    ("GET", "/admin/llm/providers"),
    # The whole evaluation surface. A benchmark run costs about $8 and
    # seven hours of provider time, so launching one is an admin act, and
    # reading the results is part of the same screen.
    ("POST", "/api/evaluation/run"),
    ("GET", "/api/evaluation/runs"),
    ("POST", "/api/evaluation/run/{run_id}/cancel"),
    # Direct retrieval endpoints bypass the graph the console asks through.
    ("POST", "/api/retrieve/sql"),
    ("POST", "/api/retrieve/vector"),
)

ANALYST_OR_BETTER = (
    # The analyst's entire surface: ask a question, get an evidence-backed
    # answer. Nothing else.
    ("POST", "/api/retrieve/financial"),
)

PUBLIC = (
    # The sign-in endpoint cannot require a token, and the health check is
    # what the platform polls.
    ("POST", "/api/auth/login"),
    ("GET", "/health"),
)


def _required_role(app, method: str, path: str) -> str | None:
    """The role a route's guard demands, or None when it has no guard."""
    for route in app.routes:
        if getattr(route, "path", None) != path:
            continue

        if method not in getattr(route, "methods", set()):
            continue

        for dependency in route.dependant.dependencies:
            required = getattr(dependency.call, "__required_role__", None)

            if required is not None:
                return required.value

        return None

    raise AssertionError(f"{method} {path} is not mounted")


@pytest.fixture(scope="module")
def app():
    from backend.main import build_app

    return build_app(deployment_mode="full")


@pytest.mark.parametrize("method,path", ADMIN_ONLY)
def test_admin_routes_require_admin(app, method, path):
    assert _required_role(app, method, path) == Role.ADMIN.value


@pytest.mark.parametrize("method,path", ANALYST_OR_BETTER)
def test_using_the_system_requires_a_signed_in_analyst(app, method, path):
    assert _required_role(app, method, path) == Role.ANALYST.value


@pytest.mark.parametrize("method,path", PUBLIC)
def test_public_routes_stay_public(app, method, path):
    assert _required_role(app, method, path) is None


def test_indexing_no_longer_uses_the_shared_admin_key(app):
    """
    /api/index/documents stacked a static X-Admin-Key on top of the role
    guard. A shared key carries no identity, no expiry and no revocation,
    and once ADMIN_API_KEY lost its published default the header check
    refused the admin it was meant to admit -- a real admin token got 401.

    The role guard replaces it.
    """
    from fastapi.security import APIKeyHeader

    for route in app.routes:
        if getattr(route, "path", None) != "/api/index/documents":
            continue

        for dependency in route.dependant.dependencies:
            assert not isinstance(dependency.call, APIKeyHeader), (
                "indexing still depends on the shared X-Admin-Key"
            )

        for sub in route.dependant.dependencies:
            for nested in sub.dependencies:
                assert not isinstance(nested.call, APIKeyHeader), (
                    "indexing still depends on the shared X-Admin-Key"
                )
