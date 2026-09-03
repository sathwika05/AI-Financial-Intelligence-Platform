"""
Where human review sits in the rail.

The order is a claim about the workflow: ask a question, configure the
models that answer it, load the corpus they answer from, review what the
pipeline refused to answer, then measure the whole thing. Review belongs
directly after ingestion because it is the queue the corpus produces, not
a property of the benchmark.

Read from the source rather than exercised in a browser. The frontend has
no test runner, and adding one to hold a five-line list would cost more
than it returns -- `tsc` already catches everything else about this file.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SHELL = ROOT / "frontend/src/admin/AdminShell.tsx"


def _nav_ids() -> list[str]:
    """The `id` of each entry in ADMIN_NAV, in declaration order."""
    source = SHELL.read_text()

    block = source[
        source.index("export const ADMIN_NAV"):
        source.index("export function AdminShell")
    ]

    return re.findall(r'id:\s*"([^"]+)"', block)


class TestTheRailOrder:
    def test_human_review_is_in_the_rail(self):
        assert "review" in _nav_ids()

    def test_it_sits_directly_after_ingestion(self):
        ids = _nav_ids()

        assert ids.index("review") == ids.index("ingestion") + 1

    def test_it_sits_before_evaluation(self):
        ids = _nav_ids()

        assert ids.index("review") < ids.index("evaluation")

    def test_nothing_was_dropped_while_inserting_it(self):
        assert _nav_ids() == [
            "home",
            "providers",
            "ingestion",
            "review",
            "evaluation",
            "security",
        ]

    def test_security_is_last(self):
        """
        After evaluation, deliberately. It is a log of what the guards
        caught rather than a place work gets done, so it reads as the
        footnote to the rail rather than a step in the sequence.
        """
        assert _nav_ids()[-1] == "security"


class TestTheSecurityDestinationExists:
    def test_the_rail_points_at_a_real_path(self):
        assert '"/security"' in SHELL.read_text()

    def test_the_router_answers_that_path(self):
        root = (ROOT / "frontend/src/Root.tsx").read_text()

        assert 'path === "/security"' in root
        assert "SecurityScreen" in root


class TestTheDestinationExists:
    def test_the_rail_points_at_a_real_path(self):
        assert '"/review"' in SHELL.read_text()

    def test_the_router_answers_that_path(self):
        """
        A rail entry with no matching branch in Root falls through to
        Home, which looks like the screen was deleted rather than
        unrouted.
        """
        root = (ROOT / "frontend/src/Root.tsx").read_text()

        assert 'path === "/review"' in root
        assert "HumanReviewScreen" in root
