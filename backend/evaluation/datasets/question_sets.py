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
"""

import json
import logging
from pathlib import Path

from backend.evaluation.schemas import EvalQuestion, IntentType
from backend.observability.logging import log_span


logger = logging.getLogger(__name__)


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
        #
        # eps is not projected either. The question asks which companies
        # grow fastest and by how much; EPS is neither asked for nor used
        # to filter here, so selecting it would contradict prompt rule 6.
        # Every ranked company already carries EPS in its `-metrics-1`
        # evidence citation, so nothing downstream loses the figure.
        expected_sql=(
            "SELECT c.ticker, c.name, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE fm.revenue_growth IS NOT NULL "
            "ORDER BY fm.revenue_growth DESC "
            "LIMIT 5"
        ),

        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "revenue_growth": 0.852},
            {"ticker": "EOG", "name": "EOG Resources, Inc.", "revenue_growth": 0.587},
            {"ticker": "CVX", "name": "Chevron Corporation", "revenue_growth": 0.535},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "revenue_growth": 0.501},
            {"ticker": "XOM", "name": "ExxonMobil Holdings Corporation", "revenue_growth": 0.441},
        ],

        expected_ranking=["NVDA", "EOG", "CVX", "AMD", "XOM"],

        # "Rank the five companies with the strongest revenue growth."
        # Same shape as valuation_002: revenue_growth DESC is what makes
        # these five the answer rather than any five companies, and the
        # question asks for them ranked.
        sql_order_requirement="top_k",
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

        # NO LONGER UNDER-SUPPORTED. This question previously carried a
        # warning that the corpus held exactly one document across all three
        # semiconductor companies, making it a measurement of missing data
        # rather than of the pipeline. Raising the per-company article cap
        # to twelve on 2026-08-19 fixed that at the source: the cohort now
        # has NVDA 3 documents, INTC 3 and AMD 1, all of them Alpha Vantage
        # articles scoring 0.84 or better on ticker relevance.
        #
        # The old warning also said not to paper over a low score with
        # reference_contexts that are absent from the corpus. That still
        # holds, and everything below is verbatim from document_chunks.
        reference_answer=(
            "NVIDIA has the most positive coverage, though all of it is "
            "indirect: Hut 8 drew Wall Street upgrades on long-term AI "
            "deals with NVIDIA reportedly worth up to $50 billion, and "
            "CoreWeave signed a multibillion-dollar agreement with Hudson "
            "River Trading for access to NVIDIA's Vera Rubin and B200 "
            "systems while raising prices on the strength of that demand. "
            "The articles are about NVIDIA's customers, and they read as a "
            "demand signal for NVIDIA. AMD is second and mildly positive: "
            "Wyoming raised its stake by 87.9%, institutional ownership "
            "stands at 71.34% and analysts hold a Moderate Buy consensus, "
            "but the coverage names high valuation and recent insider sales "
            "as risks. Intel is last and genuinely mixed despite the "
            "headline: SoftBank holding 67% of its U.S. equity portfolio in "
            "Intel reads as confidence, but the coverage points out the "
            "concentration came from Intel's stock nearly tripling rather "
            "than from any new purchase, and calls the valuation expensive "
            "given a recent price drop and dilution from Intel's own share "
            "offering. A correct answer distinguishes coverage volume from "
            "sentiment and does not treat the SoftBank position as a fresh "
            "vote of confidence."
        ),

        # Verbatim from document_chunks, one or two per company so the
        # ranking below is traceable to text rather than asserted.
        reference_contexts=[
            "CoreWeave Inc. has secured a multiyear, multibillion-dollar "
            "agreement with Hudson River Trading, granting Hudson River "
            "access to Nvidia's Vera Rubin and B200 AI systems. This deal "
            "highlights Wall Street's increasing demand for Nvidia's "
            "advanced AI chips for tasks like training trading models and "
            "analyzing data. CoreWeave has been raising prices for its AI "
            "cloud services, driven by this high demand and its early "
            "validation of Nvidia's new platforms.",

            "Hut 8 Corp. (HUT) stock is experiencing a significant surge "
            "due to massive long-term AI deals with Nvidia, repositioning "
            "the company from a crypto miner to a power-first AI "
            "infrastructure operator. These deals, reportedly totaling up "
            "to $50 billion over 30 years for its Texas data centers, have "
            "led to bullish upgrades and higher price targets from numerous "
            "Wall Street firms.",

            "The State of Wyoming significantly increased its holdings in "
            "Advanced Micro Devices (AMD) by 87.9% in Q2, purchasing an "
            "additional 2,540 shares to bring its total to 5,431 shares "
            "valued at $3.16 million. Institutional investors now own "
            "71.34% of AMD, with many funds increasing their stakes. "
            "Despite strong Q2 results, a \"Moderate Buy\" consensus from "
            "analysts, and a target price of $546.87, the stock faces risks "
            "due to high valuation and recent insider sales.",

            "SoftBank Group has made Intel (NasdaqGS: INTC) the largest "
            "component of its U.S. equity portfolio, with the stock "
            "representing nearly 67% of its disclosed holdings. This "
            "significant concentration signals a strong vote of confidence "
            "from SoftBank in Intel's AI and foundry roadmap, aligning with "
            "Intel's recent strategic shifts and capital raises.",

            "SoftBank Group's latest 13F filing reveals that Intel (INTC) "
            "now constitutes 67% of its U.S. stock portfolio, valued at "
            "$12.1 billion as of June 30. However, this high concentration "
            "is due to Intel's stock nearly tripling in the last quarter, "
            "not new purchases by Masayoshi Son, as SoftBank held the exact "
            "same number of shares.",
        ],

        # Now grounded in coverage of all three rather than in one company
        # having evidence and the others none. NVDA's coverage is uniformly
        # positive demand news; AMD's is positive with named risks; INTC's
        # leads with a confidence signal that its own follow-up coverage
        # walks back, and adds an expensive valuation and dilution. The
        # order is unchanged from before, but it is now supported.
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
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 33.20827, "eps": 6.53, "revenue_growth": 0.852},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "pe_ratio": 119.75893, "eps": 3.92, "revenue_growth": 0.501},
            {"ticker": "META", "name": "Meta Platforms, Inc.", "pe_ratio": 20.566315, "eps": 26.54, "revenue_growth": 0.28},
            {"ticker": "GOOGL", "name": "Alphabet Inc.", "pe_ratio": 17.101908, "eps": 19.92, "revenue_growth": 0.242},
            {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 26.77518, "eps": 17.97, "revenue_growth": 0.177},
        ],

        # SQL cannot produce the ordering this question asks for. The
        # ranking is over valuation, revenue growth, current market
        # performance and document sentiment; SQL holds the first two, and
        # the other two arrive from the market and vector branches. No
        # ORDER BY it could write would be the requested ranking, so the
        # ORDER BY revenue_growth DESC in the reference above is one
        # defensible choice rather than the answer.
        #
        # This is about SQL's semantic contract, not about the reranker
        # overwriting the order downstream: even judged in isolation, there
        # is no correct SQL ordering here to grade against.
        #
        # Concretely, a query returning exactly these five companies with
        # identical values scored 0.0 for sorting by pe_ratio instead.
        sql_order_requirement="none",

        # Written around what the documents can support, not around the
        # numbers.
        #
        # context_entity_recall extracts entities from THIS text, extracts
        # entities from the retrieved contexts, and scores the intersection
        # over the entities found here — reference_contexts is not involved.
        # An earlier version of this answer opened "NVIDIA leads on growth
        # with 85.2% revenue growth at a 34.5 P/E", and every figure in it
        # enlarged the denominator with something a news article can never
        # contain. The metric read 0.0714: roughly one entity matched out of
        # fourteen, most of the misses being P/E ratios and growth
        # percentages that live in financial_metrics.
        #
        # The figures are not lost. sql grades the values, and ranking
        # grades the order, both at 1.0 — so restating them here only
        # measured the document corpus against something that was never in
        # it.
        #
        # What remains are claims a reader could check against the retrieved
        # articles, with company names as the entities that should actually
        # be recoverable. Coverage gaps are stated rather than filled in:
        # AMD and Alphabet have no documents, and an answer that invented
        # sentiment for them would be wrong.
        reference_answer=(
            "All five cohort companies now have recent coverage, so the "
            "sentiment component rests on documents rather than on absence. "
            "NVIDIA has the strongest coverage, and it is indirect: Hut 8 "
            "was upgraded on long-term AI deals with NVIDIA, and CoreWeave "
            "signed a multibillion-dollar agreement with Hudson River "
            "Trading for access to NVIDIA systems while raising prices on "
            "demand. The coverage describes NVIDIA's customers rather than "
            "NVIDIA itself, and reads as a demand signal. AMD's coverage is "
            "mildly positive, reporting institutional accumulation and a "
            "Moderate Buy consensus, tempered by high valuation and insider "
            "sales. Microsoft appears favourably by comparison, placed ahead "
            "of Meta in the AI race. Alphabet is mixed: it fell as part of a "
            "broad Big Tech decline, while YouTube is spending aggressively "
            "to keep creators from Netflix. Meta is weakest, with its AI "
            "manifesto questioned as positioning rather than capability. "
            "Every claim should cite the retrieved document, financial or "
            "market evidence for that company."
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
        # One chunk per cohort member, each taken verbatim from
        # document_chunks after the 2026-08-19 reseed. All five are present
        # for the first time: raising the per-company article cap to twelve
        # gave AMD and Alphabet coverage they previously lacked, so the
        # earlier note about their absence no longer applies.
        #
        # The NVIDIA chunk is about CoreWeave, not NVIDIA. That is what the
        # corpus holds — Alpha Vantage scores the article 0.96 relevant to
        # NVDA because it turns on demand for NVIDIA hardware — and the
        # reference has to match the corpus rather than the ideal article.
        reference_contexts=[
            "CoreWeave Inc. has secured a multiyear, multibillion-dollar "
            "agreement with Hudson River Trading, granting Hudson River "
            "access to Nvidia's Vera Rubin and B200 AI systems. This deal "
            "highlights Wall Street's increasing demand for Nvidia's "
            "advanced AI chips for tasks like training trading models and "
            "analyzing data. CoreWeave has been raising prices for its AI "
            "cloud services, driven by this high demand and its early "
            "validation of Nvidia's new platforms.",

            "The State of Wyoming significantly increased its holdings in "
            "Advanced Micro Devices (AMD) by 87.9% in Q2, purchasing an "
            "additional 2,540 shares to bring its total to 5,431 shares "
            "valued at $3.16 million. Institutional investors now own "
            "71.34% of AMD, with many funds increasing their stakes. "
            "Despite strong Q2 results, a \"Moderate Buy\" consensus from "
            "analysts, and a target price of $546.87, the stock faces risks "
            "due to high valuation and recent insider sales.",

            "Meta's market capitalization of $1.39 trillion significantly "
            "lags behind Amazon ($2.87 trillion), Microsoft ($3.60 "
            "trillion), and Alphabet ($4.19 trillion) in the AI race, "
            "despite CEO Mark Zuckerberg's 14-page AI manifesto. Even "
            "private AI rival Anthropic is nearing or surpassing Meta's "
            "valuation, highlighting investors' diminished view of Meta's "
            "social media business and AI strategy compared to its tech "
            "giant peers.",

            "YouTube is offering millions to popular creators for exclusive "
            "video uploads, aiming to prevent them from simultaneously "
            "working with Netflix. This strategy includes direct financing "
            "of programs and sharing portions of major brand deals. Netflix "
            "has been paying YouTubers to cross-post content, seeking to "
            "attract younger audiences and expand its subscriber base, "
            "which YouTube views as a threat to its viewership and "
            "advertising revenue.",

            "Mark Zuckerberg's \"AI manifesto,\" \"The Future is for "
            "Everyone,\" outlines a vision of democratized AI and personal "
            "superintelligence agents. However, the article questions "
            "whether Meta's past actions and current capabilities align "
            "with this ambitious vision, particularly concerning its "
            "commitment to open-source principles and its standing in the "
            "competitive AI landscape. It suggests that Meta's public "
            "stance might be more of a PR move to position itself amidst "
            "stronger AI contenders.",
        ],

        # Ordered by revenue growth, which is the widest spread in this cohort
        # (85.2% down to 17.7%) and therefore the most defensible single
        # ordering. Adjust if the intended weighting differs — this order is
        # what precision@k, MRR and NDCG@k are graded against.
        expected_ranking=["NVDA", "AMD", "META", "GOOGL", "MSFT"],
    ),
]


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
    path = Path(__file__).parent / "generated_ground_truth.json"

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
SMOKE_QUESTIONS: list[EvalQuestion] = (
    VALUATION_QUESTIONS
    + GROWTH_QUESTIONS
    + SENTIMENT_QUESTIONS
    + MIXED_QUESTIONS
)


QUESTION_SETS: dict[str, list[EvalQuestion]] = {
    # Exactly the generated questions. The hand-written valuation_002 and
    # growth_001 are NOT added on top: valuation_002 asks the same thing as
    # the generated valuation_profitable_15, differing only in spelling
    # "five" for 5 and a redundant market_cap > 0. Counting both would
    # measure one question twice and weight it double in the pass rate.
    #
    # They are not lost — "smoke" below is where they live, which is the
    # set that should stay stable across runs anyway.
    "valuation": GENERATED_VALUATION,
    "growth": GENERATED_GROWTH,

    # Authored sets: reference answers and contexts need judgement about
    # what a good answer says and which documents support it.
    "sentiment": SENTIMENT_QUESTIONS,
    "mixed": MIXED_QUESTIONS,

    "smoke": SMOKE_QUESTIONS,

    "all": (
        GENERATED_VALUATION
        + GENERATED_GROWTH
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
