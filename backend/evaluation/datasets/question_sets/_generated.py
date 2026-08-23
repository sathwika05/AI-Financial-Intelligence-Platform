"""
Loader for the SQL-derived sets.

Valuation and growth ground truth is read out of the database by
generate_ground_truth.py rather than written by hand, because a reseed
moves every fundamental. This module only reads the file it produces.
"""
import json
import logging
from pathlib import Path

from backend.evaluation.schemas import EvalQuestion, IntentType
from backend.observability.logging import log_span

logger = logging.getLogger(__name__)


def _load_generated(set_name: str) -> list[EvalQuestion]:
    """
    Load the SQL-derived questions for one set.

    Ground truth for valuation and growth is read out of the database by
    generate_ground_truth.py rather than written here, because a reseed
    moves every fundamental. Rebuilding four questions by hand took most of
    a session; sixty is not slow, it is infeasible.

    Returns an empty list when the file is missing, so the authored sets
    still run on a checkout where the generator has not been run yet. The
    file is regenerated with:

        uv run python -m backend.evaluation.datasets.generate_ground_truth
    """
    path = Path(__file__).parent.parent / "generated_ground_truth.json"

    if not path.exists():
        logger.warning(
            "[QUESTION_SETS] %s not found — the '%s' set is empty. Run "
            "generate_ground_truth to build it.",
            path.name,
            set_name,
        )
        return []

    payload = json.loads(path.read_text())

    questions: list[EvalQuestion] = []

    for question_id, entry in payload.get("questions", {}).items():
        if entry.get("set") != set_name:
            continue

        questions.append(
            EvalQuestion(
                question_id=question_id,
                question=entry["question"],
                expected_intent=IntentType(entry["expected_intent"]),
                expected_tools=entry.get("expected_tools", []),
                expected_sql=entry["expected_sql"],
                expected_sql_result=entry["expected_sql_result"],
                expected_ranking=entry.get("expected_ranking", []),
                sql_order_requirement=entry.get(
                    "sql_order_requirement",
                    "top_k",
                ),
            )
        )

    return questions


GENERATED_VALUATION = _load_generated("valuation")
GENERATED_GROWTH = _load_generated("growth")


# The four hand-written questions above, kept as a fast regression set.
#
# Every fix this session was measured against these, so they carry the
# history: valuation_002 is the question whose fabricated 1.0 exposed the
# SQL provenance bug, and mixed_001 is the only one joining both tables,
# which is what caught fm.market_cap. They run in roughly twelve minutes,
# where the full hundred takes over four hours — short enough to run on
# every change.