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
    transcripts, and chunks are only loosely tied to their company. The
    sentiment question is phrased around news coverage for that reason.

Never set `expected_sql_result=[]` as a placeholder. An empty list is not the
same as leaving it unset: the SQL evaluator skips its comparison only when the
value is None, and an empty reference scores a spurious sql_accuracy of 1.0.
Leave the field out until real rows are available.
"""

from backend.evaluation.schemas import EvalQuestion, IntentType
from backend.observability.logging import log_span


VALUATION_QUESTIONS: list[EvalQuestion] = [
    # valuation_001 is disabled. Its ground truth is still valid against the
    # seed — re-enable by uncommenting, no re-verification needed.
    # EvalQuestion(
    #     question_id="valuation_001",
    #     question=(
    #         "Which five technology companies have the lowest P/E ratios "
    #         "while also having positive EPS? Rank them from lowest to "
    #         "highest P/E ratio."
    #     ),
    #     expected_intent=IntentType.VALUATION,
    #     expected_tools=["planner", "sql"],
    #
    #     expected_sql=(
    #         "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps "
    #         "FROM companies c "
    #         "JOIN financial_metrics fm ON fm.company_id = c.id "
    #         "WHERE c.sector = 'Technology' "
    #         "AND fm.pe_ratio > 0 "
    #         "AND fm.eps > 0 "
    #         "ORDER BY fm.pe_ratio ASC "
    #         "LIMIT 5"
    #     ),
    #
    #     # Exactly the rows the query above returns against the seed. INTC is
    #     # absent by design: it has a null P/E and negative EPS.
    #     expected_sql_result=[
    #         {"ticker": "ADBE", "name": "Adobe Inc.", "pe_ratio": 14.749572, "eps": 17.49},
    #         {"ticker": "CRM", "name": "Salesforce, Inc.", "pe_ratio": 22.348028, "eps": 8.62},
    #         {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 27.492489, "eps": 17.97},
    #         {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 34.532207, "eps": 6.52},
    #         {"ticker": "AAPL", "name": "Apple Inc.", "pe_ratio": 35.082172, "eps": 8.64},
    #     ],
    #
    #     # The question defines the order, so this is not a judgement call:
    #     # ascending P/E.
    #     expected_ranking=["ADBE", "CRM", "MSFT", "NVDA", "AAPL"],
    # ),
    EvalQuestion(
        question_id="valuation_002",
        question=(
            "Which five profitable technology companies have the smallest "
            "market capitalizations? Rank them from smallest to largest market cap."
        ),
        expected_intent=IntentType.VALUATION,
        expected_tools=["planner", "sql"],
    
        expected_sql=(
            "SELECT c.ticker, c.name, c.market_cap, fm.eps "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.sector = 'Technology' "
            "AND fm.eps > 0 "
            "AND c.market_cap IS NOT NULL "
            "AND c.market_cap > 0 "
            "ORDER BY c.market_cap ASC "
            "LIMIT 5"
        ),
    
        expected_sql_result=[
            {
                "ticker": "ADBE",
                "name": "Adobe Inc.",
                "market_cap": 102543073280,
                "eps": 17.49,
            },
            {
                "ticker": "AMD",
                "name": "Advanced Micro Devices, Inc.",
                "market_cap": 800222937088,
                "eps": 3.91,
            },
            {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "market_cap": 3668516798464,
                "eps": 17.97,
            },
            {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "market_cap": 4423641726976,
                "eps": 8.64,
            },
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corporation",
                "market_cap": 5453358039040,
                "eps": 6.52,
            },
        ],
    
        expected_ranking=[
            "ADBE",
            "AMD",
            "MSFT",
            "AAPL",
            "NVDA",
        ],
    ),
]


GROWTH_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question_id="growth_001",
        question=(
            "Rank the five companies with the strongest revenue growth "
            "based on the latest available financial metrics."
        ),
        expected_intent=IntentType.GROWTH,
        expected_tools=["planner", "sql"],

        # Ranks on revenue growth alone: the seed has no eps_growth column,
        # and asking for it would penalise the pipeline for not returning a
        # figure the database cannot produce.
        expected_sql=(
            "SELECT c.ticker, c.name, fm.revenue_growth, fm.eps "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE fm.revenue_growth IS NOT NULL "
            "ORDER BY fm.revenue_growth DESC "
            "LIMIT 5"
        ),

        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "revenue_growth": 0.852, "eps": 6.52},
            {"ticker": "EOG", "name": "EOG Resources, Inc.", "revenue_growth": 0.587, "eps": 12.85},
            {"ticker": "CVX", "name": "Chevron Corporation", "revenue_growth": 0.535, "eps": 10.38},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "revenue_growth": 0.501, "eps": 3.91},
            {"ticker": "XOM", "name": "ExxonMobil Holdings Corporation", "revenue_growth": 0.441, "eps": 7.76},
        ],

        expected_ranking=["NVDA", "EOG", "CVX", "AMD", "XOM"],
    ), 
]


SENTIMENT_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question_id="sentiment_001",
        question=(
            "Which semiconductor companies have the most positive sentiment "
            "in recent news coverage? Rank them and support the ranking with "
            "evidence from the retrieved documents."
        ),
        expected_intent=IntentType.SENTIMENT,
        expected_tools=["planner", "vector"],

        reference_answer=(
            "AMD carries the most positive coverage: it is raising up to $5 "
            "billion in what would be its largest investment-grade bond sale, "
            "tied to demand from the artificial intelligence boom. Intel's "
            "coverage is mixed — it posted its strongest revenue growth in "
            "over fifteen years, but trades more than 30% below its recent "
            "peak after a stock offering unsettled investors, and it is "
            "weighing a return to the memory market. NVIDIA's coverage is the "
            "least company-specific, consisting largely of index movement "
            "summaries and reporting on other firms."
        ),

        # Verbatim from document_chunks for these tickers. The corpus is
        # general market news and several chunks discuss other companies, so
        # this is what good retrieval can actually return, not an ideal.
        reference_contexts=[
            "Advanced Micro Devices Inc. is planning to raise as much $5 billion "
            "in what could be the chipmaker's biggest-ever investment-grade bond "
            "sale, adding to a wave of debt tied to the artificial intelligence boom.",

            "Intel just posted its strongest revenue growth in over 15 years, yet "
            "shares sit more than 30% below their recent peak after a massive stock "
            "offering rattled investors.",

            "Intel's CEO said this week that the chip maker may return to the memory "
            "market, potentially making it a challenger to Micron and SK Hynix.",
        ],

        # Only three semiconductor companies exist in the seed.
        expected_ranking=["AMD", "INTC", "NVDA"],
    ),
]


MIXED_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question_id="mixed_001",
        question=(
            "Rank the five best AI-related stocks using valuation, revenue "
            "growth, current market performance, and sentiment from recent "
            "company documents. Explain the evidence behind the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        # The AI cohort is named explicitly: `companies` has no industry
        # column, so membership cannot be derived in SQL.
        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('NVDA', 'AMD', 'MSFT', 'GOOGL', 'META') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 34.532207, "eps": 6.52, "revenue_growth": 0.852},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "pe_ratio": 125.368286, "eps": 3.91, "revenue_growth": 0.501},
            {"ticker": "META", "name": "Meta Platforms, Inc.", "pe_ratio": 22.17802, "eps": 26.57, "revenue_growth": 0.28},
            {"ticker": "GOOGL", "name": "Alphabet Inc.", "pe_ratio": 17.369793, "eps": 19.93, "revenue_growth": 0.242},
            {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 27.492489, "eps": 17.97, "revenue_growth": 0.177},
        ],

        reference_answer=(
            "NVIDIA leads on growth with 85.2% revenue growth at a 34.5 P/E, "
            "the strongest growth in the cohort at a moderate multiple. AMD "
            "grows quickly at 50.1% but is the most expensive on valuation at "
            "a 125.4 P/E. Meta and Alphabet are the cheapest on earnings at "
            "22.2 and 17.4 P/E with moderate growth of 28.0% and 24.2%. "
            "Microsoft is the slowest grower of the five at 17.7%. Every "
            "conclusion should cite the retrieved financial or document "
            "evidence for that company."
        ),

        # Chosen because each chunk carries AI-relevant, company-specific
        # evidence for a name in the cohort. An earlier draft used a chunk
        # about CoreWeave, which is filed under NVDA but is not about NVDA —
        # that mismatch zeroed context precision, recall and entity recall.
        reference_contexts=[
            "Advanced Micro Devices Inc. is planning to raise as much $5 billion "
            "in what could be the chipmaker's biggest-ever investment-grade bond "
            "sale, adding to a wave of debt tied to the artificial intelligence boom.",

            "Microsoft just signed off on IREN's first major AI data center, and "
            "NVIDIA piled on with a rare technical designation, sending shares "
            "surging.",

            "While its two biggest cloud rivals soared past the market this year, "
            "one hyperscaler kept beating earnings estimates and still watched its "
            "stock fall.",
        ],

        # Ordered by revenue growth, which is the widest spread in this cohort
        # (85.2% down to 17.7%) and therefore the most defensible single
        # ordering. Adjust if the intended weighting differs — this order is
        # what precision@k, MRR and NDCG@k are graded against.
        expected_ranking=["NVDA", "AMD", "META", "GOOGL", "MSFT"],
    ),
]


QUESTION_SETS: dict[str, list[EvalQuestion]] = {
    "valuation": VALUATION_QUESTIONS,
    "growth": GROWTH_QUESTIONS,
    "sentiment": SENTIMENT_QUESTIONS,
    "mixed": MIXED_QUESTIONS,
    "all": (
        VALUATION_QUESTIONS
        + GROWTH_QUESTIONS
        + SENTIMENT_QUESTIONS
        + MIXED_QUESTIONS
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
