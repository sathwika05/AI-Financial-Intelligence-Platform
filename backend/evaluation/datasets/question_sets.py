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

RESEEDING INVALIDATES EVERYTHING BELOW. The seed pulls live fundamentals from
Yahoo, so market caps, P/E ratios and EPS all move, and the membership of a
"top five" can change outright — a reseed on 2026-08-18 dropped NVDA out of
the smallest-market-cap five and brought CRM in. The pipeline then answers
correctly and the benchmark marks it wrong, which looks exactly like a
regression and is not one.

After every reseed, re-run each `expected_sql` against the database and paste
the rows back in. The queries are written to be runnable as-is for that
reason.
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
    #         {"ticker": "ADBE", "name": "Adobe Inc.", "pe_ratio": 15.103448, "eps": 16.82},
    #         {"ticker": "CRM", "name": "Salesforce, Inc.", "pe_ratio": 22.734526, "eps": 8.4},
    #         {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 27.622198, "eps": 17.39},
    #         {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 34.457886, "eps": 6.53},
    #         {"ticker": "AAPL", "name": "Apple Inc.", "pe_ratio": 35.044724, "eps": 8.72},
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
                "market_cap": 100980899840,
                "eps": 16.82,
            },
            {
                "ticker": "CRM",
                "name": "Salesforce, Inc.",
                "market_cap": 156404432896,
                "eps": 8.4,
            },
            {
                "ticker": "AMD",
                "name": "Advanced Micro Devices, Inc.",
                "market_cap": 826032324608,
                "eps": 3.85,
            },
            {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "market_cap": 3566861025280,
                "eps": 17.39,
            },
            {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "market_cap": 4459835424768,
                "eps": 8.72,
            },
        ],

        expected_ranking=[
            "ADBE",
            "CRM",
            "AMD",
            "MSFT",
            "AAPL",
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
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "revenue_growth": 0.852, "eps": 6.53},
            {"ticker": "EOG", "name": "EOG Resources, Inc.", "revenue_growth": 0.587, "eps": 13.17},
            {"ticker": "CVX", "name": "Chevron Corporation", "revenue_growth": 0.535, "eps": 10.54},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "revenue_growth": 0.501, "eps": 3.85},
            {"ticker": "XOM", "name": "ExxonMobil Holdings Corporation", "revenue_growth": 0.441, "eps": 7.83},
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

        # UNDER-SUPPORTED BY THE CURRENT CORPUS — read this before trusting
        # a score from this question.
        #
        # The semiconductor cohort is NVDA, AMD and INTC, and after the news
        # relevance filter the corpus holds exactly one document across all
        # three of them: the NVIDIA chunk below. A question asking which of
        # three companies has the most positive sentiment cannot be answered
        # from coverage of one, so this currently measures a gap in the data
        # rather than the quality of the pipeline.
        #
        # Left in place rather than deleted because the shape of the
        # question is sound and it will start measuring something real as
        # soon as the corpus carries semiconductor coverage again. Two ways
        # to get there: seed more news for these tickers, or lower
        # MIN_NEWS_RELEVANCE, though the measured distribution says
        # everything below 0.75 is mostly mislinked.
        #
        # Do not "fix" a low score here by adding reference_contexts that
        # are not in the corpus. That is what the previous version did — it
        # cited an AMD bond sale and two Intel stories, all of which the
        # reseed removed, and the pipeline was then graded against evidence
        # that could not be retrieved at any quality level.
        reference_answer=(
            "Only NVIDIA has recent coverage in the corpus, and it is "
            "positive: ARK's ETFs sold Roblox to buy a substantial NVIDIA "
            "position, which the coverage frames as continued confidence in "
            "NVIDIA's growth. AMD and Intel have no documents, so their "
            "sentiment is unknown rather than neutral, and a ranking that "
            "places either above NVIDIA is unsupported. The correct answer "
            "reports the absence rather than inferring a position from it."
        ),

        # Verbatim from document_chunks. The single chunk the semiconductor
        # cohort currently has.
        reference_contexts=[
            "Cathie Wood's ARK ETFs have strategically rebalanced their "
            "portfolio by selling a significant amount of Roblox stock and "
            "acquiring a substantial number of Nvidia shares. This move "
            "reflects ARK's continued confidence in Nvidia's growth potential "
            "within the evolving tech landscape.",
        ],

        # NVDA first because it is the only company with evidence. AMD and
        # INTC follow in a fixed order so the metric is deterministic, but
        # nothing in the corpus justifies preferring one over the other —
        # treat any ranking score here as weak.
        expected_ranking=["NVDA", "AMD", "INTC"],
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

        # The cohort is the `ai` theme in company_themes, and the pipeline
        # now resolves it there before any branch runs. It is written as an
        # explicit ticker list rather than a join through themes because
        # that is what the pipeline produces: the resolver hands the SQL
        # generator the tickers it already looked up, so the generator never
        # needs to know the taxonomy exists.
        #
        # Keep this list and seeds/themes.py in step. A test pins the `ai`
        # membership to exactly these five for that reason.
        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('NVDA', 'AMD', 'MSFT', 'GOOGL', 'META') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 34.457886, "eps": 6.53, "revenue_growth": 0.852},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "pe_ratio": 131.42857, "eps": 3.85, "revenue_growth": 0.501},
            {"ticker": "META", "name": "Meta Platforms, Inc.", "pe_ratio": 22.22539, "eps": 25.6, "revenue_growth": 0.28},
            {"ticker": "GOOGL", "name": "Alphabet Inc.", "pe_ratio": 17.364967, "eps": 19.81, "revenue_growth": 0.242},
            {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 27.622198, "eps": 17.39, "revenue_growth": 0.177},
        ],

        reference_answer=(
            "NVIDIA leads on growth with 85.2% revenue growth at a 34.5 P/E, "
            "the strongest growth in the cohort at a moderate multiple. AMD "
            "grows quickly at 50.1% but is by far the most expensive on "
            "valuation at a 131.4 P/E. Meta and Alphabet are the cheapest on "
            "earnings at 22.2 and 17.4 P/E with moderate growth of 28.0% and "
            "24.2%. Microsoft is the slowest grower of the five at 17.7%. "
            "Document evidence is uneven across the cohort — only NVIDIA, "
            "Microsoft and Meta have recent coverage in the corpus — so "
            "sentiment should be reported as unavailable for AMD and "
            "Alphabet rather than inferred. Every conclusion should cite the "
            "retrieved financial or document evidence for that company."
        ),

        # Read from the corpus rather than written from memory, and chosen
        # to be reachable: with candidate resolution in place, vector search
        # is restricted to documents belonging to the five cohort companies,
        # so anything outside that set can never be retrieved and would
        # score zero however well the pipeline performed.
        #
        # The previous entries described an AMD bond sale and a Microsoft
        # IREN data centre. Both were true of the corpus at the time and
        # neither survived the reseed, which is what drove context
        # precision, recall and entity recall to 0.0 — the pipeline was
        # being graded against evidence that no longer existed.
        #
        # Each of these carries company-specific AI content for a different
        # cohort member. AMD and Alphabet are absent because the corpus has
        # no documents for them, which is a fact about the data and not
        # something to paper over with a loosely related chunk.
        reference_contexts=[
            "Cathie Wood's ARK ETFs have strategically rebalanced their "
            "portfolio by selling a significant amount of Roblox stock and "
            "acquiring a substantial number of Nvidia shares. This move "
            "reflects ARK's continued confidence in Nvidia's growth potential "
            "within the evolving tech landscape.",

            "The move highlights Microsoft's strategy to position Teams as a "
            "comprehensive customer interaction platform and signifies the "
            "growing importance of AI voice agents in contact center "
            "architectures, creating new opportunities for partners to "
            "provide integration and managed services.",

            "Meta Platforms (META) declined amid legal challenges and AI "
            "strategy uncertainties.",
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
