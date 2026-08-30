"""
Links out to the tools that explain a run, once it is deployed.

CloudWatch holds what the containers printed and LangSmith holds the
graph's trace hierarchy. Both are external products with better interfaces
than anything worth rebuilding here, so the admin UI links to them rather
than proxying them.

The URLs differ per deployment -- a different AWS account, region and log
group, a different LangSmith project -- so they are configuration, not
constants. Empty means this deployment has nowhere to point, which is the
normal state on a laptop.
"""
import pytest

from backend.auth.roles import Role


class TestTheEndpoint:
    def test_it_is_admin_only(self):
        """
        A CloudWatch console URL names the account and the log group. Not a
        credential, but not something a public page should carry either.
        """
        from backend.main import build_app

        app = build_app(deployment_mode="full")

        routes = [
            r for r in app.routes
            if getattr(r, "path", "") == "/api/admin/external-links"
        ]

        assert routes, "the external links route is not mounted"

        for route in routes:
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required

    def test_it_is_absent_from_the_public_deployment(self):
        from backend.main import build_app

        paths = {
            getattr(r, "path", "")
            for r in build_app(deployment_mode="portfolio").routes
        }

        assert "/api/admin/external-links" not in paths


class TestWhatItReports:
    def test_a_configured_link_is_returned(self):
        from backend.api.admin_links_routes import _links

        payload = _links(
            cloudwatch="https://console.aws.amazon.com/cloudwatch/home#logsV2:log-groups",
            langsmith="https://smith.langchain.com/o/abc/projects/p/xyz",
        )

        assert payload["cloudwatch"]["url"].startswith("https://console.aws")
        assert payload["cloudwatch"]["configured"] is True
        assert payload["langsmith"]["configured"] is True

    def test_an_unset_link_reports_which_setting_is_missing(self):
        """
        On a laptop there is nowhere to point. The screen should say which
        variable to set rather than showing a dead link or nothing at all.
        """
        from backend.api.admin_links_routes import _links

        payload = _links(cloudwatch="", langsmith="")

        assert payload["cloudwatch"]["configured"] is False
        assert "CLOUDWATCH_LOGS_URL" in payload["cloudwatch"]["detail"]
        assert "LANGSMITH_PROJECT_URL" in payload["langsmith"]["detail"]

    def test_a_non_https_link_is_refused(self):
        """
        These are rendered as anchors in an admin page. A javascript: value
        in configuration would execute on click.
        """
        from backend.api.admin_links_routes import _links

        payload = _links(
            cloudwatch="javascript:alert(1)",
            langsmith="http://smith.langchain.com/x",
        )

        assert payload["cloudwatch"]["configured"] is False
        assert payload["langsmith"]["configured"] is False

    def test_whitespace_is_not_a_configured_link(self):
        from backend.api.admin_links_routes import _links

        assert _links(cloudwatch="   ", langsmith="")["cloudwatch"]["configured"] is False
