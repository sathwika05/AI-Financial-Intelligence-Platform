"""
The security feed is an admin surface.

Every row holds a query somebody typed -- including the ones a guard
refused, which are exactly the queries most worth not publishing. The
guard on the route matters as much as the handler.

Asserted against the route table rather than by exercising the handlers:
what a mounted route demands is a property of the app, and reading it
directly means the guard cannot be satisfied by a fixture that grants
itself a token.
"""
from backend.auth.roles import Role
from backend.main import build_app


FEED = "/admin/security/events"


def _routes(path: str, mode: str = "full"):
    return [
        r for r in build_app(deployment_mode=mode).routes
        if getattr(r, "path", "") == path
    ]


class TestTheFeedIsMounted:
    def test_the_route_exists(self):
        assert _routes(FEED), "the security events route is not mounted"


class TestOnlyAdminsReachIt:
    def test_it_demands_admin(self):
        for route in _routes(FEED):
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required


class TestThePublicDeploymentHasNoFeed:
    """
    Portfolio mode has no accounts at all -- everyone is an analyst. A log
    of refused queries must not be mounted where nothing can guard it.
    """

    def test_the_feed_is_absent(self):
        assert _routes(FEED, mode="portfolio") == []
