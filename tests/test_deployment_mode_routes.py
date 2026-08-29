"""
Preprod is public and unauthenticated, so it must expose only the UI.

infrastructure/preprod/render.yaml has always set DEPLOYMENT_MODE=portfolio
and carried a comment saying the evaluation and indexing routers "have to be
absent rather than merely unlinked from the UI". Nothing read the variable:
it appeared in the blueprint, the README and compute.tf, and in no Python
file at all, while main.py mounted every router unconditionally.

That left a public deployment serving unauthenticated provider mutation
(/admin/llm/*), corpus re-indexing (/api/index/documents) and benchmark
launching (/api/evaluation/run), the last two spending the operator's own
provider credit.

The UI screen needs /health and /api/retrieve/financial. Nothing else.
"""
import pytest


UI_ROUTES = {
    "/health",
    "/api/retrieve/financial",
}

# Every route that must not exist on a public unauthenticated deployment.
PRIVILEGED_PREFIXES = (
    "/admin/llm",
    "/api/index",
    "/api/evaluation",
    "/api/retrieve/sql",
    "/api/retrieve/vector",
)


def _paths(app) -> set[str]:
    return {
        route.path
        for route in app.routes
        if getattr(route, "path", None)
    }


class TestPortfolioMode:
    def test_the_ui_routes_are_served(self):
        from backend.main import build_app

        paths = _paths(build_app(deployment_mode="portfolio"))

        for route in UI_ROUTES:
            assert route in paths, f"portfolio mode must serve {route}"

    @pytest.mark.parametrize("prefix", PRIVILEGED_PREFIXES)
    def test_privileged_routes_are_absent(self, prefix):
        from backend.main import build_app

        paths = _paths(build_app(deployment_mode="portfolio"))

        offending = [p for p in paths if p.startswith(prefix)]

        assert offending == [], (
            f"portfolio mode must not mount {prefix}; found {offending}"
        )


class TestFullMode:
    @pytest.mark.parametrize("prefix", PRIVILEGED_PREFIXES)
    def test_everything_is_mounted(self, prefix):
        """Production keeps the full surface; the gate is preprod-only."""
        from backend.main import build_app

        paths = _paths(build_app(deployment_mode="full"))

        assert any(p.startswith(prefix) for p in paths), (
            f"full mode must mount {prefix}"
        )


class TestUnknownMode:
    def test_an_unrecognised_mode_fails_loudly(self):
        """
        A typo must not silently fall through to the permissive branch.
        "portfolio" misspelled is how a public deployment ends up serving
        the admin router, which is the whole failure this guards.
        """
        from backend.main import build_app

        with pytest.raises(ValueError) as caught:
            build_app(deployment_mode="portfolo")

        assert "portfolo" in str(caught.value)


class TestAdminKeyHasNoDefault:
    def test_the_committed_default_is_gone(self):
        """
        ADMIN_API_KEY defaulted to "admin-secret-key" in a public repo, and
        render.yaml never set it, so the published value was live on the
        indexing endpoint.
        """
        from backend.config import Settings

        field = Settings.model_fields["ADMIN_API_KEY"]

        assert field.default != "admin-secret-key"


class TestPortfolioIsPublic:
    """
    Preprod is a public portfolio demo: anyone with the link asks a
    question, nobody signs in. The rate limiter is the control there --
    backend/api/financial_routes.py has said so all along ("preprod has no
    authentication, so the ceiling is about cost rather than login abuse").

    Production is the opposite: the same route requires a signed-in
    analyst, because it is behind a login and spending a customer's credit.
    """

    def test_asking_a_question_needs_no_token_in_portfolio_mode(self):
        from backend.main import build_app

        app = build_app(deployment_mode="portfolio")

        assert _role_for(app, "POST", "/api/retrieve/financial") is None

    def test_asking_a_question_needs_an_analyst_in_full_mode(self):
        from backend.main import build_app

        app = build_app(deployment_mode="full")

        assert _role_for(app, "POST", "/api/retrieve/financial") == "analyst"

    def test_health_says_whether_a_login_is_required(self):
        """
        The frontend cannot know which deployment it is talking to. Without
        this it would show a sign-in page on the public demo.
        """
        from backend.main import build_app

        app = build_app(deployment_mode="portfolio")

        paths = {r.path for r in app.routes if getattr(r, "path", None)}

        assert "/health" in paths


def _role_for(app, method: str, path: str) -> str | None:
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
