"""
Golden questions for the benchmark.

Every expected value here was read out of the seeded database rather than
written from memory, so the questions are answerable with the data that
actually exists. Where the seed could not support the question as originally
phrased, the question was narrowed instead of the ground truth being invented
— a benchmark that asks for something absent measures nothing.

Constraints the seed imposes, and how each is handled:

  - `financial_metrics` has pe_ratio, eps and revenue_growth only. There is no
    eps_growth column, so the growth question ranks on revenue growth alone.
  - `companies` has `sector` but no `industry`, so "semiconductor" cannot be
    expressed in SQL. The sentiment question names its three tickers directly.
  - Only NVDA, AMD and INTC are semiconductors in the seed, so that question
    asks for three companies, not five.
  - The document corpus is general market news, not filings or earnings
    transcripts. The sentiment question is phrased around news coverage for
    that reason. Coverage is company-linked through Alpha Vantage's
    ticker_sentiment relevance rather than by keyword, but a relevant article
    is often about a company's customers or rivals rather than the company
    itself — the NVIDIA documents are about CoreWeave and Hut 8. Reference
    contexts have to reflect that, not the article one would prefer existed.

Never set `expected_sql_result=[]` as a placeholder. An empty list is not the
same as leaving it unset: the SQL evaluator skips its comparison only when the
value is None, and an empty reference scores a spurious sql_accuracy of 1.0.
Leave the field out until real rows are available.

RESEEDING INVALIDATES EVERYTHING BELOW. The seed pulls live fundamentals from
Yahoo, so market caps, P/E ratios and EPS all move, and the membership of a
"top five" can change outright — a reseed on 2026-08-18 dropped NVDA out of
the smallest-market-cap five and brought CRM in. The pipeline then answers
correctly and the benchmark marks it wrong, which looks exactly like a
regression and is not one.

After every reseed, rebuild the ground truth. Two commands, because the two
halves are maintained differently:

    uv run python -m backend.evaluation.datasets.generate_ground_truth
    uv run python -m backend.evaluation.datasets.verify_ground_truth

The first re-runs every specification in question_bank.py and writes the
rows it gets back — that covers the sixty derived valuation and growth
questions, which nobody should be maintaining by hand. The second checks
everything, derived and authored alike, and exits non-zero if anything
drifted, so it can gate a run.

The questions written out below are the authored half. Their expected rows
still need re-running by hand, and their reference answers and contexts need
judgement about what a good answer says and which documents support it — a
script that generated those would only ever confirm its own output. The
queries are written to be runnable as-is for that reason.

Layout
------

Each intent owns a module, and each module owns its questions:

    valuation.py   ORIGINALS + GENERATED  -> QUESTIONS   30
    growth.py      ORIGINALS + GENERATED  -> QUESTIONS   30
    sentiment.py   ORIGINALS + AUTHORED   -> QUESTIONS   25
    mixed.py       ORIGINALS + AUTHORED   -> QUESTIONS   15

ORIGINALS is the hand-written question that predates the set. For
valuation, growth and sentiment it is excluded from QUESTIONS, because a
generated or authored question now asks the same thing and counting both
would weight it double in the pass rate. It still runs, in "smoke". Only
mixed counts its original, because nothing duplicates mixed_001.

This module combines them, and is the single place evaluation reads from:
benchmark_runner and verify_ground_truth both import get_question_set or
QUESTION_SETS from here, and never from an intent module directly.
"""
import os

from backend.evaluation.datasets.question_sets import (
    growth,
    mixed,
    sentiment,
    valuation,
)
from backend.evaluation.schemas import EvalQuestion
from backend.observability.logging import log_span


# Names the old flat module exported. Kept so an import that predates the
# package still resolves.
VALUATION_QUESTIONS = valuation.ORIGINALS
GROWTH_QUESTIONS = growth.ORIGINALS
SENTIMENT_QUESTIONS = sentiment.QUESTIONS
MIXED_QUESTIONS = mixed.ORIGINALS
GENERATED_VALUATION = valuation.GENERATED
GENERATED_GROWTH = growth.GENERATED


SMOKE_QUESTIONS: list[EvalQuestion] = (
    valuation.ORIGINALS
    + growth.ORIGINALS
    + sentiment.SMOKE
    + mixed.ORIGINALS
)


_EVERY_QUESTION: dict[str, EvalQuestion] = {
    question.question_id: question
    for questions in (
        valuation.QUESTIONS,
        growth.QUESTIONS,
        sentiment.QUESTIONS,
        mixed.QUESTIONS,
        SMOKE_QUESTIONS,
    )
    for question in questions
}


FOCUS_QUESTIONS: list[EvalQuestion] = [
    _EVERY_QUESTION[question_id]
    for question_id in (
        part.strip()
        for part in os.environ.get("FOCUS_QUESTIONS", "").split(",")
    )
    if question_id in _EVERY_QUESTION
]


QUESTION_SETS: dict[str, list[EvalQuestion]] = {
    "valuation": valuation.QUESTIONS,
    "growth": growth.QUESTIONS,
    "sentiment": sentiment.QUESTIONS,
    "mixed": mixed.QUESTIONS,

    "smoke": SMOKE_QUESTIONS,

    # A scratch set, named by the FOCUS_QUESTIONS environment variable as a
    # comma-separated list of question ids.
    #
    # When a run surfaces a handful of broken questions, the fix needs a
    # loop measured in minutes against exactly those questions. A sentiment
    # run is two and a half hours and a mixed run longer, which is too slow
    # to iterate against — the same argument that justifies "smoke", except
    # that what to look at is chosen per investigation.
    #
    # Empty when the variable is unset, and unknown ids are skipped rather
    # than guessed at: a typo should measure nothing, not something else.
    "focus": FOCUS_QUESTIONS,

    # The hundred: valuation 30, growth 30, sentiment 25, mixed 15.
    "all": (
        valuation.QUESTIONS
        + growth.QUESTIONS
        + sentiment.QUESTIONS
        + mixed.QUESTIONS
    ),
}

@log_span("name")
def get_question_set(name: str) -> list[EvalQuestion]:
    normalized = name.strip().lower()

    if normalized not in QUESTION_SETS:
        supported = ", ".join(sorted(QUESTION_SETS))
        raise ValueError(
            f"Unknown question set '{name}'. Supported: {supported}"
        )

    return QUESTION_SETS[normalized]
