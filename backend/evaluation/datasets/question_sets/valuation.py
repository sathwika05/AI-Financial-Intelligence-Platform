"""
The valuation set: valuation questions, generated from the database.

ORIGINALS holds the hand-written question that predates the generator. It
is deliberately NOT counted in QUESTIONS: it asks the same thing as one of
the generated questions, so counting both would weight it double in the
pass rate. It still runs, in the smoke set.
"""
from backend.evaluation.schemas import EvalQuestion, IntentType
from backend.evaluation.datasets.question_sets._generated import _load_generated


ORIGINALS: list[EvalQuestion] = [
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
    #
    #     # "the five ... lowest P/E ratios": the sort selects the members,
    #     # so this is top_k rather than plain ranking when re-enabled.
    #     sql_order_requirement="top_k",
    # ),
    EvalQuestion(
        question_id="valuation_002",
        question=(
            "Which five profitable technology companies have the smallest "
            "market capitalizations? Rank them from smallest to largest market cap."
        ),
        expected_intent=IntentType.VALUATION,
        expected_tools=["planner", "sql"],
    
        # eps is the profitability filter, not output. The question asks
        # which companies qualify and how large they are, never for their
        # EPS, and prompt rule 6 tells the generator to select only the
        # columns the question needs — so projecting it here graded the
        # model down for following its own instructions.
        #
        # Nothing downstream needs it either: evidence_builder emits a
        # `<TICKER>-metrics-1` citation carrying P/E, EPS, revenue growth
        # and market cap for every ranked company, so the evidence for
        # "profitable" exists whether or not SQL returns the column. When
        # SQL did also return it, the analysis node flagged the pair as
        # "two evidence records largely duplicate the same financial
        # metrics" and lowered that company's confidence to 0.43.
        expected_sql=(
            "SELECT c.ticker, c.name, c.market_cap "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.sector = 'Technology' "
            "AND fm.eps > 0 "
            "AND c.market_cap IS NOT NULL "
            "AND c.market_cap > 0 "
            "ORDER BY c.market_cap ASC "
            "LIMIT 5"
        ),
    
        # Mirrors expected_sql above, so eps is absent here too — the rows
        # are what that query returns, not a wish list. market_cap is a
        # float because the column is double precision; the ints that were
        # here before matched only because DataCompy compares numerically.
        #
        # THE LIMIT IS CURRENTLY NON-BINDING — read this before trusting a
        # top_k membership score from this question.
        #
        # Six Technology companies have positive EPS, and Salesforce is one
        # of them, but the 2026-08-19 reseed returned a null market_cap for
        # CRM and HD. Yahoo reports no marketCap and no sharesOutstanding
        # for either right now; only enterpriseValue comes back, which is
        # market cap plus debt minus cash and therefore a different figure
        # that must not be written into this column.
        #
        # `AND c.market_cap > 0` drops CRM, leaving exactly five qualifying
        # rows for a query asking for five. Membership is satisfied by any
        # query with the right filters, so top_k grading currently proves
        # only the ordering, not the selection. That is a weaker test than
        # it looks — treat a passing membership score here as uninformative
        # until Yahoo returns the field again.
        #
        # The previous run is what this guards against: CRM sat second at
        # $156B, and its disappearance pulled NVDA in from sixth place.
        expected_sql_result=[
            {
                "ticker": "ADBE",
                "name": "Adobe Inc.",
                "market_cap": 108207448064.0,
            },
            {
                "ticker": "AMD",
                "name": "Advanced Micro Devices, Inc.",
                "market_cap": 766373527552.0,
            },
            {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "market_cap": 3572801208320.0,
            },
            {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "market_cap": 4543167856640.0,
            },
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corporation",
                "market_cap": 5252323999744.0,
            },
        ],

        expected_ranking=[
            "ADBE",
            "AMD",
            "MSFT",
            "AAPL",
            "NVDA",
        ],

        # "Which five ... have the smallest market capitalizations? Rank
        # them from smallest to largest." The sort decides which five
        # companies appear at all, so an arbitrary LIMIT 5 is a wrong
        # answer even with the filters right — and the question then asks
        # for those five in a stated order on top.
        #
        # Previously graded as plain ordered comparison, which checked the
        # sequence but never that these were the true five smallest.
        sql_order_requirement="top_k",
    ),
]



GENERATED = _load_generated("valuation")

QUESTIONS = GENERATED
