"""
The dashboard has to be served by something.

Locally two servers run: Vite serves the React app and proxies /api and
/health through to FastAPI. In production there is no Vite -- only this
container -- so nothing answered at "/" and the deployed stack was an API
with no user interface, returning 404 at its own front door.

The built assets were already inside the image, copied by `COPY . .` and
then ignored. This serves them.

The frontend calls the API with relative paths (`fetch("/api/auth/login")`),
so serving both from one origin needs no rebuild and no CORS.
"""
import pytest
from starlette.testclient import TestClient


def _client(mode="full"):
    from backend.main import build_app

    # Not used as a context manager on purpose: entering it runs the
    # lifespan, which connects to Postgres and creates tables. These tests
    # are about route matching, not startup.
    return TestClient(build_app(deployment_mode=mode))


class TestServingTheDashboard:
    def test_the_root_serves_the_built_frontend(self):
        response = _client().get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_a_client_side_route_falls_back_to_the_app(self):
        """
        React Router owns paths the server has never heard of. Returning
        404 for them means a refresh on any screen but the first breaks.
        """
        response = _client().get("/evaluation")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.parametrize(
        "screen", ["/providers", "/ingestion", "/review", "/evaluation"]
    )
    def test_every_admin_screen_survives_a_refresh(self, screen):
        """
        Each of these is a real URL the rail links to, so each has to
        answer on a cold request rather than only after client-side
        navigation. /review was added last and is the one a new catch-all
        ordering would most plausibly miss.
        """
        response = _client().get(screen)

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestTheApiIsNotShadowed:
    def test_health_is_matched_before_the_catch_all(self):
        """
        A catch-all registered carelessly swallows this, and the load
        balancer's health check starts receiving HTML -- which fails the
        check and takes the service down.

        Asserted on the route table rather than by issuing a request:
        calling /health opens a database connection, and doing that from a
        TestClient's own event loop leaves the shared async engine's pool
        bound to a loop that later tests do not use.
        """
        from starlette.routing import Match

        from backend.main import build_app

        app = build_app(deployment_mode="full")
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [],
        }

        matched = [
            route
            for route in app.routes
            if route.matches(scope)[0] == Match.FULL
        ]

        assert matched, "/health matches nothing"
        # Starlette takes the first full match, so the order is the
        # behaviour: health must come before the dashboard fallback.
        assert matched[0].name == "health"

    def test_an_unknown_api_path_is_still_a_404(self):
        """
        A missing endpoint must look missing. Serving index.html for
        /api/anything turns a typo in the frontend into a silent success
        that returns HTML where JSON was expected.
        """
        response = _client().get("/api/does-not-exist")

        assert response.status_code == 404

    def test_the_docs_are_still_reachable(self):
        response = _client().get("/docs")

        assert response.status_code == 200


class TestWithoutABuild:
    def test_the_api_still_starts_when_the_frontend_was_never_built(
        self, tmp_path, monkeypatch
    ):
        """
        A checkout that has never run `npm run build` has no dist/. The
        API must not refuse to start over a missing UI.
        """
        import backend.main as main

        monkeypatch.setattr(main, "_frontend_dist", lambda: tmp_path / "nope")

        client = TestClient(main.build_app(deployment_mode="full"))

        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/").status_code == 404
