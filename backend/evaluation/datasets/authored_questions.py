"""
The authored question sets — SENTIMENT and MIXED.

FILL THIS IN BY HAND. That is the point of the file, not a limitation of it.

Valuation and growth questions are generated, because their correct answer
IS a query result: run the SQL, get rows, those rows are true by definition.
Nothing here works that way. There is no sentiment column, so "which company
has the most positive coverage" has no query that answers it — someone has
to read the articles and decide.

And it must be a person, not a model. The pipeline uses an LLM to read those
chunks and rank the companies. Ground truth written by another LLM would
share its blind spots, so the two would agree on the same mistakes and the
benchmark would report a pass. The SQL sets do not have this problem because
Postgres is the arbiter. Here, you are.

TARGET
    SENTIMENT   25   (1 written, 24 to go)
    MIXED       15   (1 written, 14 to go)

HOW TO FILL ONE IN

  1. Read the corpus for the companies you want to ask about:

         uv run python -m backend.evaluation.datasets.read_corpus INTC NVDA AMD
         uv run python -m backend.evaluation.datasets.read_corpus --sector Energy
         uv run python -m backend.evaluation.datasets.read_corpus --coverage
         uv run python -m backend.evaluation.datasets.read_corpus --themes

  2. Add `--python` to print a chunk as a quoted, wrapped string you can
     paste straight into reference_contexts.

  3. Write the question, the reference answer, the contexts, the ranking.

  4. Check your work:

         uv run python -m backend.evaluation.datasets.verify_ground_truth

     It fails if a reference context is not in document_chunks.

FIVE THINGS THAT HAVE ALREADY GONE WRONG HERE

  Paraphrasing a context. reference_contexts is matched as TEXT. A trimmed
  sentence or a straightened quote scores 0.0, silently, looking exactly
  like a retrieval failure. Two questions once cited an AMD bond story and a
  Microsoft data-centre story that a reseed had deleted, and context
  precision, recall and entity recall all read 0.0 while retrieval was
  working perfectly. Copy from read_corpus. Never retype.

  Citing evidence the cohort cannot reach. Vector search is restricted to
  the companies in the question, so a context belonging to a company outside
  the cohort can never be retrieved and scores 0.0 however well the pipeline
  performs.

  Writing a richer answer than the corpus supports. context_recall measures
  how much of your reference_answer the retrieved contexts support. An
  answer making claims about five companies when the corpus covers two will
  score badly no matter how good retrieval is. Say only what the documents
  say.

  Putting numbers in the reference answer. context_entity_recall extracts
  entities from your answer and looks for them in the retrieved DOCUMENTS. A
  P/E ratio lives in financial_metrics and appears in no news article, so
  every figure you add enlarges the denominator with something unmatchable.
  One answer opened "NVIDIA leads with 85.2% revenue growth at a 34.5 P/E"
  and scored 0.0714. The figures are not lost — the sql and ranking
  evaluators grade them.

  Hedging. RAGAS multiplies response_relevancy by zero if its judge calls
  the answer noncommittal. A correct, well-cited answer scored 0.0 for
  saying its evidence was indirect. Write plainly: "NVIDIA's coverage is
  positive" rather than "NVIDIA's coverage may suggest possible positive
  sentiment, though it is difficult to say".

WHAT MAKES A GOOD QUESTION HERE

  Vary the shape, do not permute one. Every bug found so far needed a
  structurally different question. Worth covering: a cohort where one
  company has no coverage; two companies whose articles contradict each
  other; coverage that is about a company's customers rather than the
  company; a cohort where the obvious answer is wrong.

  Intel is the model case. One chunk calls SoftBank's 67% position "a strong
  vote of confidence"; another says the 67% came from the stock tripling
  rather than any purchase. Ranking Intel last requires noticing the second
  retracts the first. No query returns that, and an answer that stops at the
  first chunk is wrong.

  For MIXED, use sectors as cohorts as well as themes. There are three
  themes covering nine companies, so fifteen theme-only questions would
  measure the same names repeatedly. Seven sectors are rankable and every
  one has full document coverage — see read_corpus --themes.
"""
from backend.evaluation.schemas import EvalQuestion, IntentType


# ── SENTIMENT ──────────────────────────────────────────────────────────
#
# Ranks companies by the tone of their recent coverage. Retrieves documents
# and nothing else, so every context IS a document and the retrieval
# metrics are scored over all of them.
#
# expected_tools is ["planner", "vector"] — no sql, no market.

SENTIMENT_AUTHORED: list[EvalQuestion] = [
    # ------------------------------------------------------------------
    # WORKED EXAMPLE — copy this block to start a new one.
    #
    # Delete nothing from it without reading the note above it first;
    # each field is here because getting it wrong cost a real score.
    # ------------------------------------------------------------------
    EvalQuestion(
        question_id="sentiment_002",
        question=(
            "Which semiconductor companies have the most positive sentiment "
            "in recent news coverage? Rank them and support the ranking "
            "with evidence from the retrieved documents."
        ),
        expected_intent=IntentType.SENTIMENT,
        expected_tools=["planner", "vector"],

        # Says what the documents say, and nothing they do not. No P/E, no
        # growth percentage: those are graded by the sql and ranking
        # evaluators, and adding them here only enlarges the entity
        # denominator with figures no article contains.
        #
        # States its conclusions plainly. "NVIDIA has the strongest
        # coverage" rather than "NVIDIA may possibly have somewhat
        # stronger coverage" — the second reads as noncommittal and zeroes
        # response_relevancy.
        reference_answer=(
            "NVIDIA has the strongest coverage, though it is indirect: Hut 8 "
            "was upgraded on long-term AI deals with NVIDIA, and CoreWeave "
            "signed a multibillion-dollar agreement with Hudson River "
            "Trading for access to NVIDIA systems while raising prices on "
            "demand. The articles describe NVIDIA's customers, and they read "
            "as a demand signal. AMD is second and mildly positive, "
            "reporting institutional accumulation and a Moderate Buy "
            "consensus against high valuation and insider sales. Intel is "
            "last. SoftBank holding 67% of its U.S. equity portfolio in "
            "Intel reads as confidence, but the coverage says that "
            "concentration came from Intel's stock nearly tripling rather "
            "than from any new purchase, and calls the valuation expensive "
            "given a recent price drop and dilution."
        ),

        # VERBATIM from document_chunks. Printed by:
        #   read_corpus NVDA AMD INTC --python
        reference_contexts=[
            "CoreWeave Inc. has secured a multiyear, multibillion-dollar "
            "agreement with Hudson River Trading, granting Hudson River "
            "access to Nvidia's Vera Rubin and B200 AI systems. This deal "
            "highlights Wall Street's increasing demand for Nvidia's "
            "advanced AI chips for tasks like training trading models and "
            "analyzing data. CoreWeave has been raising prices for its AI "
            "cloud services, driven by this high demand and its early "
            "validation of Nvidia's new platforms.",

            "SoftBank Group's latest 13F filing reveals that Intel (INTC) "
            "now constitutes 67% of its U.S. stock portfolio, valued at "
            "$12.1 billion as of June 30. However, this high concentration "
            "is due to Intel's stock nearly tripling in the last quarter, "
            "not new purchases by Masayoshi Son, as SoftBank held the exact "
            "same number of shares.",
        ],

        # The order the reference answer argues for.
        expected_ranking=["NVDA", "AMD", "INTC"],
    ),

    # ------------------------------------------------------------------
    # 23 more. Suggested coverage, from read_corpus --coverage:
    #
    #   - a cohort where one company has no documents (say so in the
    #     answer; do not invent sentiment for it)
    #   - two companies whose articles disagree
    #   - a sector cohort rather than a theme
    #   - coverage that is about customers rather than the company
    #   - a case where the loudest coverage is not the most positive
    # ------------------------------------------------------------------
]


# ── MIXED ──────────────────────────────────────────────────────────────
#
# Ranks a cohort on valuation, growth, live market data and document
# sentiment together. All four branches run, so contexts are a mix of
# document chunks, SQL rows and market rows — only the document subset is
# scored for retrieval quality.
#
# expected_tools is ["planner", "sql", "vector", "market"].
#
# sql_order_requirement is "none" for these. The ranking is over four
# signals and SQL holds two, so no ORDER BY it could write would be the
# requested ranking. Any ordering in expected_sql is one defensible choice,
# not the answer.
#
# Phrase the question as a ranking over a named cohort. "Which five
# companies combine growth with a low P/E" routed to MIXED when it was
# meant to be GROWTH — MIXED here means multi-SOURCE, not multi-metric.

MIXED_AUTHORED: list[EvalQuestion] = [
    # ------------------------------------------------------------------
    # 14 to write. See mixed_001 in question_sets.py for a full worked
    # example including expected_sql and the cohort ticker list.
    #
    # Cohorts available — read_corpus --themes:
    #   themes    AI (5), Cloud Computing (4), Semiconductors (3)
    #   sectors   Financial Services (12), Healthcare (10), Technology (7),
    #             Consumer Cyclical (6), Energy (5), Industrials (5),
    #             Communication Services (4)
    #
    # Every sector has full document coverage, so any of them works as a
    # cohort. Three themes across fifteen questions would not.
    # ------------------------------------------------------------------
]
