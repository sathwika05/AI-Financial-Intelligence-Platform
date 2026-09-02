"""
The escalation queue is an admin surface.

Every row holds a query somebody typed and the draft the system decided was
too weak to show them. That is exactly the material an analyst should not
be able to page through, so the guard matters as much as the handler.

These assert the route table rather than exercising the handlers: what a
mounted route demands is a property of the app, and reading it directly
means the guard cannot be satisfied by a fixture that grants itself a
token.
"""
from backend.auth.roles import Role
from backend.main import build_app


QUEUE = "/admin/escalations"
RESOLVE = "/admin/escalations/{escalation_id}/resolve"


def _routes(path: str, mode: str = "full"):
    return [
        r for r in build_app(deployment_mode=mode).routes
        if getattr(r, "path", "") == path
    ]


class TestTheQueueIsMounted:
    def test_the_listing_route_exists(self):
        assert _routes(QUEUE), "the escalation queue route is not mounted"

    def test_the_resolve_route_exists(self):
        assert _routes(RESOLVE), "the resolve route is not mounted"


class TestOnlyAdminsReachIt:
    def test_listing_demands_admin(self):
        for route in _routes(QUEUE):
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required

    def test_resolving_demands_admin(self):
        for route in _routes(RESOLVE):
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required


class TestThePublicDeploymentHasNoQueue:
    """
    Portfolio mode has no accounts at all — everyone is an analyst. A
    queue of withheld reports must not be mounted where nothing can guard
    it.
    """

    def test_the_queue_is_absent(self):
        assert _routes(QUEUE, mode="portfolio") == []

    def test_resolving_is_absent(self):
        assert _routes(RESOLVE, mode="portfolio") == []
