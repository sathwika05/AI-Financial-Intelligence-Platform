"""
The routes the dashboard calls must exist, and each must be defined once.

Two failures hid behind each other here, both introduced by one edit and
neither caught by any test.

The edit that made EDGAR indexing return 202 added the new handler and
left the old synchronous one further down the file. Python keeps the last
definition, so the old one won -- the fix was in the tree, passing review,
and not running. Nothing failed: the route still worked, just slowly.

The same edit dropped @router.get("/edgar/filings") entirely. The button
that calls it returned 404 in production, and the only way to find out was
to press it.

Route tables are exactly the kind of thing unit tests miss, because every
individual handler still works.
"""
import ast
import pathlib
import re

import pytest


ROUTES_FILE = pathlib.Path("backend/api/ingestion_routes.py")
FRONTEND = pathlib.Path("frontend/src")


class TestNothingIsDefinedTwice:
    def test_no_handler_is_defined_twice(self):
        """
        A second definition silently replaces the first. That is how the
        old synchronous EDGAR handler kept running after being replaced.
        """
        tree = ast.parse(ROUTES_FILE.read_text())

        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        duplicated = sorted({n for n in names if names.count(n) > 1})

        assert not duplicated, (
            f"{ROUTES_FILE} defines these more than once, and only the last "
            f"one runs: {duplicated}"
        )

    def test_no_route_path_is_registered_twice(self):
        """The same method and path twice means one of them is dead."""
        from backend.api.ingestion_routes import router

        seen = [
            (sorted(r.methods)[0], r.path)
            for r in router.routes
            if getattr(r, "methods", None)
        ]

        duplicated = sorted({r for r in seen if seen.count(r) > 1})

        assert not duplicated, f"registered more than once: {duplicated}"


class TestEveryPathTheDashboardCallsExists:
    def test_the_frontend_calls_nothing_that_is_missing(self):
        """
        The dashboard's fetch calls, checked against the mounted app.

        A path the client asks for and the server does not serve is a 404
        the user finds, because nothing else looks at both sides.
        """
        from backend.main import build_app

        app = build_app(deployment_mode="full")
        served = {getattr(r, "path", None) for r in app.routes}

        missing = sorted(
            path for path in _paths_the_frontend_calls()
            if not _is_served(path, served)
        )

        assert not missing, (
            f"the dashboard calls these, and the app does not serve them: "
            f"{missing}"
        )


def _is_served(path: str, served: set[str]) -> bool:
    """
    Whether the app serves this path, or a route continuing from it.

    _paths_the_frontend_calls cuts a template at the first ${, so
    `/api/evaluation/claims/${claimId}` arrives here as
    `/api/evaluation/claims` -- a prefix of the real route rather than a
    route itself. Treating that as missing reports a 404 that cannot
    happen, so a served route continuing with a path parameter counts.

    Deliberately narrow: only `<path>/{` matches, so `/api/evaluation` is
    still not satisfied by `/api/evaluation/runs`. A truncated call has to
    reach an actual route's parameter, not merely share a namespace.
    """
    if path in served:
        return True

    return any(route.startswith(f"{path}/{{") for route in served)


def _paths_the_frontend_calls() -> set[str]:
    """
    Every literal /api or /admin path in the frontend's source.

    Template interpolation is cut at the first ${, so
    `/api/ingestion/edgar/filings?${query}` contributes the path without
    its query string -- which is what the route table holds.
    """
    found: set[str] = set()

    for source in FRONTEND.rglob("*.ts"):
        for match in re.finditer(r'[`"\'](/(?:api|admin|health)[^`"\']*)', source.read_text()):
            path = match.group(1)
            path = path.split("?")[0].split("${")[0].rstrip("/")

            # A path built from a variable segment cannot be compared to a
            # literal route, so those are left out rather than guessed at.
            if path and "${" not in path:
                found.add(path)

    return found
