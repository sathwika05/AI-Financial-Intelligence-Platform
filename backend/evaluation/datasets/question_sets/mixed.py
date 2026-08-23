"""
The mixed set: mixed_001 plus 14 authored questions.

Unlike the other three, ORIGINALS IS counted in QUESTIONS — mixed_001 is
the `ai` theme cohort and nothing authored duplicates it.

Every question here needs five fields beyond the sentiment three:
expected_sql, expected_sql_result and sql_order_requirement, which is
always "none" because the ranking spans four signals and SQL holds two.
"""
from backend.evaluation.schemas import EvalQuestion, IntentType


ORIGINALS: list[EvalQuestion] = [
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


AUTHORED: list[EvalQuestion] = [
    # ------------------------------------------------------------------
    # 14 to write. See mixed_001 in question_sets.py for a full worked
    # example including expected_sql and the cohort ticker list.
    #
    # Each candidate below is a whole question, ready to paste. What is
    # left is expected_sql, expected_sql_result, reference_answer,
    # reference_contexts and expected_ranking.
    #
    # Cohorts available — read_corpus --themes:
    #   themes    AI (5), Cloud Computing (4), Semiconductors (3)
    #   sectors   Financial Services (12), Healthcare (10), Technology (7),
    #             Consumer Cyclical (6), Energy (5), Industrials (5),
    #             Communication Services (4)
    #
    # Every sector has full document coverage, so any of them works as a
    # cohort. Three themes across fifteen questions would not.
    #
    # All fifty companies have exactly one financial_metrics row, so the
    # SQL branch is complete for every cohort below. The gaps are all on
    # the document side, and they are noted where they matter.
    #
    # Every one of these takes sql_order_requirement "none": the ranking
    # is over four signals and SQL holds two, so no ORDER BY it could
    # write would be the requested order.
    #
    # Where a question names a sector or a theme rather than listing
    # tickers, run it once and look at what the SQL branch emits before
    # writing expected_sql — mixed_001 lists tickers because that is what
    # the theme resolver hands the generator, and a sector cohort may
    # produce a c.sector filter instead. sql_equivalence compares queries,
    # so the golden has to match the shape the pipeline actually produces.
    #
    # THE SHAPE, AS JSON
    #
    # Nothing reads JSON question specs — generated_ground_truth.json is
    # for the SQL-derived sets only, and these have to land here as
    # EvalQuestion objects. This is a fill-in template for drafting one
    # away from Python syntax, and for seeing the whole field list at once.
    #
    #   {
    #     "question_id": "mixed_002",
    #     "question": "Rank the energy sector companies using valuation, ...",
    #
    #     "expected_intent": "MIXED",
    #     "expected_tools": ["planner", "sql", "vector", "market"],
    #
    #     "expected_sql": "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, ...",
    #     "expected_sql_result": [
    #       {"ticker": "EOG", "name": "EOG Resources, Inc.",
    #        "pe_ratio": 11.834371, "eps": 12.86, "revenue_growth": 0.587}
    #     ],
    #     "sql_order_requirement": "none",
    #
    #     "reference_answer": "<yours>",
    #     "reference_contexts": ["<yours, one whole chunk, verbatim>"],
    #     "expected_ranking": ["<yours, best to worst>"]
    #   }
    #
    # Fixed for every question here: expected_intent, expected_tools (four
    # branches, not two) and sql_order_requirement, which is always "none".
    #
    # From the database, never typed: expected_sql_result. Run expected_sql
    # and paste the rows. Confirm expected_sql itself by running the
    # question once and reading what the SQL branch emits — a sector cohort
    # may produce a c.sector filter rather than a ticker list.
    #
    # Yours: the last three, under the same rules as the sentiment set.
    # Contexts whole and verbatim, only companies inside the cohort, the
    # answer saying only what the documents say, no P/E or growth figures,
    # no hedging.
    #
    # One caveat on drafting in JSON: its strings are single-line, so a
    # context pasted there cannot be diffed against read_corpus --python
    # output, which already emits the wrapped Python form. Copy contexts
    # straight into the Python block instead, and keep JSON for the fields
    # around them.
    #
    #
    # mixed_002   XOM CVX COP EOG SLB
    #   "Rank the energy sector companies using valuation, revenue growth,
    #    current market performance and sentiment from recent company
    #    documents. Explain the evidence behind the ranking."
    #
    #   Five names, all with real coverage, and the documents run from
    #   analyst targets to DCF valuation pieces.
    #
    #   NOT the Venezuelan rig counts. Both Venezuela documents (chunks 205
    #   and 206) carry a real headline and a body of "- Reuters", so the
    #   facts in them live in documents.title, which retrieval never
    #   returns. sentiment_015 cited them and had to give them up.
    #
    EvalQuestion(
        question_id="mixed_002",
        question=(
            "Rank the energy sector companies using valuation, revenue "
            "growth, current market performance and sentiment from recent "
            "company documents. Explain the evidence behind the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],
        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('XOM', 'CVX', 'COP', 'EOG', 'SLB') "
            "ORDER BY fm.revenue_growth DESC"
        ),
        expected_sql_result=[
            {"ticker": "EOG", "name": "EOG Resources, Inc.", "pe_ratio": 11.834371, "eps": 12.86, "revenue_growth": 0.587},
            {"ticker": "CVX", "name": "Chevron Corporation", "pe_ratio": 19.804619, "eps": 10.39, "revenue_growth": 0.535},
            {"ticker": "XOM", "name": "ExxonMobil Holdings Corporation", "pe_ratio": 21.35604, "eps": 7.78, "revenue_growth": 0.441},
            {"ticker": "COP", "name": "ConocoPhillips", "pe_ratio": 17.842592, "eps": 7.56, "revenue_growth": 0.355},
            {"ticker": "SLB", "name": "SLB N.V.", "pe_ratio": 26.121952, "eps": 2.05, "revenue_growth": 0.05},
        ],
        sql_order_requirement="none",
        reference_answer=(
            "EOG Resources (EOG) balances top-tier fundamental growth and "
            "valuation metrics with steady broker backing. EOG delivers the "
            "highest revenue growth in the group alongside a low P/E multiple "
            "and solid financial health, while maintaining Overweight and "
            "Equal-Weight ratings across major Wall Street brokers.\n\nExxonMobil "
            "(XOM) combines robust current market momentum with massive "
            "strategic deals, including a long-term midstream agreement with "
            "Targa Resources and upstream contract awards for Rovuma LNG Phase 1 "
            "development in Mozambique.\n\nChevron (CVX) offers strong long-term "
            "market outperformance, international asset expansion via Equinor's "
            "stake acquisition in Namibia, and price target hikes from Morgan "
            "Stanley.\n\nConocoPhillips (COP) is backed by widespread bullish "
            "analyst price target increases from Morgan Stanley and Argus "
            "Research, alongside key executive hires, though slightly tempered "
            "by a price target trim from Barclays.\n\nSLB N.V. (SLB) exhibits "
            "strong document sentiment and operational momentum—highlighted by a "
            "major Brunei Shell Petroleum contract award, long-term returns, and "
            "a DCF intrinsic discount—but its fundamental metrics lag the cohort "
            "with the lowest revenue growth and highest P/E multiple."
        ),
        reference_contexts=[
            # EOG
            "EOG Resources offers a compelling value play with low valuation, strong profitability, solid financial health, and moderate growth potential.",
            "Wells Fargo  analyst Sam Margolin   maintains EOG Resources (NYSE:EOG) with a Overweight and lowers the price target from $196 to $193.",
            "Morgan Stanley  analyst Devin McDermott   maintains EOG Resources (NYSE:EOG) with a Equal-Weight and raises the price target from $156 to $157.",
            "Barclays  analyst Betty Jiang   maintains EOG Resources (NYSE:EOG) with a Equal-Weight and lowers the price target from $153 to $147.",

            # XOM
            "ExxonMobil shares rise as oil tops $85 amid Strait of Hormuz disruptions, while the energy sector gains about 40% year to date.",
            "Targa Resources Corp. (NYSE: TRGP) (&#34;Targa&#34; or the &#34;Company&#34;) today announced the execution of new long-term, integrated midstream agreements with subsidiaries of ExxonMobil, further strengthening the",
            "https://corporate.exxonmobil.com/locations/mozambique/mozambique-newsroom/exxonmobil-mozambique-and-area-4-coventurers-award-over-1-b-usd-in-contracts-for-rovuma-lng",
            "Morgan Stanley  analyst Devin McDermott   maintains ExxonMobil Holdings (NYSE:XOM) with a Overweight and raises the price target from $168 to $177.",

            # CVX
            "Chevron (NYSE:CVX) has outperformed the market over the past 5 years by 5.03% on an annualized basis producing an average annual return of 16.35%. Currently, Chevron has a market capitalization of $411.82 billion.",
            "https://www.equinor.com/news/20260818-equinor-chevron-namibia-exploration-licence",
            "Morgan Stanley  analyst Devin McDermott   maintains Chevron (NYSE:CVX) with a Overweight and raises the price target from $210 to $218.",

            # COP
            "Morgan Stanley  analyst Devin McDermott   maintains ConocoPhillips (NYSE:COP) with a Overweight and raises the price target from $147 to $151.",
            "Argus Research  analyst Bill Selesky   maintains ConocoPhillips (NYSE:COP) with a Buy and raises the price target from $136 to $153.",
            "Barclays  analyst Betty Jiang   maintains ConocoPhillips (NYSE:COP) with a Overweight and lowers the price target from $155 to $150.",
            "In early August 2026, Chord Energy reported past second-quarter results showing higher total production volumes year-on-year, sharply higher revenue of US$2.17 billion, a swing to net income of US$525.19 million, and confirmed new production guidance, a US$1.30 per-share base dividend, and completion of a US$265.92 million buyback tranche. The company also announced that long-serving executive Shannon Kinney will depart to become General Counsel at ConocoPhillips, while CEO Danny Brown...",

            # SLB
            "Global energy technology company SLB (NYSE:SLB) today announced it has been awarded a contract by Brunei Shell Petroleum (BSP) to support production restoration from shut-in wells across multiple offshore fields.The",
            "SLB stock has delivered a 119.7% total return over the past five years, and the current Discounted Cash Flow (DCF) intrinsic value estimate still points to a sizeable 41.9% implied discount to the share price, even though market based valuation multiples look roughly in line with peers. For investors, that mix raises the question of whether the recent gains have fully reflected the long term cash flow potential that the DCF is capturing. Over the past five years SLB has returned 119.7%,..."
        ],
        expected_ranking=["EOG", "XOM", "CVX", "COP", "SLB"],
    ),

    # mixed_003   GE BA CAT HON UPS
    #   "Rank the industrials companies on valuation, revenue growth,
    #    current market performance and the sentiment of their recent
    #    documents, and explain what drives the order."
    #
    #   Honeywell's 51.5% six-month decline is the case where market
    #   performance and document tone should agree and valuation may not.
    #
    EvalQuestion(
        question_id="mixed_003",
        question=(
            "Rank the industrials companies on valuation, revenue growth, "
            "current market performance and the sentiment of their recent "
            "documents, and explain what drives the order."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('GE', 'BA', 'CAT', 'HON', 'UPS') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "CAT", "name": "Caterpillar, Inc.", "pe_ratio": 35.05546, "eps": 23.26, "revenue_growth": 0.24},
            {"ticker": "GE", "name": "GE Aerospace", "pe_ratio": 40.641514, "eps": 8.48, "revenue_growth": 0.211},
            {"ticker": "BA", "name": "The Boeing Company", "pe_ratio": 77.37411, "eps": 2.78, "revenue_growth": 0.08},
            {"ticker": "UPS", "name": "United Parcel Service, Inc.", "pe_ratio": 19.066914, "eps": 5.38, "revenue_growth": 0.076},
            {"ticker": "HON", "name": "Honeywell International Inc.", "pe_ratio": 8.393695, "eps": 26.01, "revenue_growth": 0.043},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       GE BA CAT HON UPS --python

        reference_answer = (
        "GE Aerospace (GE) ranks first overall in this industrials cohort, "
        "followed by Caterpillar (CAT), The Boeing Company (BA), Honeywell International (HON), and United Parcel Service (UPS).\n\n"
        "GE Aerospace (GE) leads the cohort by pairing market-leading operational execution and analyst sentiment with strong demand momentum. "
        "GE's document coverage highlights record revenue, strong defense contract momentum (including a U.S. Air Force contract for the GEK800 engine), "
        "and Q2-driven analyst revisions raising its fair value estimate to ~$404.90, which outweighs near-term capacity and supply constraints.\n\n"
        "Caterpillar (CAT) ranks second, backed by exceptional long-term market outperformance (33.53% 5-year average annual return, outperforming the market by 21.71%) "
        "and strategic workforce initiatives, though its high valuation multiple tempers its overall ranking.\n\n"
        "The Boeing Company (BA) ranks third. Boeing benefits from major international contract approvals, including a $4.5B U.S. State Department "
        "approval for Qatar's purchase of KC-46A aerial refueling aircraft, providing solid revenue pipeline support despite wider aerospace sector volatility.\n\n"
        "Honeywell International (HON) ranks fourth with mixed signals. While supported by executive appointments across its Process Technology and Building Automation "
        "units and a $20B backlog, Honeywell faces operational headwinds from supplier underperformance and analyst price target cuts.\n\n"
        "United Parcel Service (UPS) ranks fifth, constrained by fundamental volume weakness. While UPS targets ~$3B in network cost savings "
        "and benefits from tariff refund processing, ongoing core U.S. package volume declines and lower historical margins keep its overall outlook capped."
    ),

    reference_contexts = [
        # GE
        "The Fair Value Estimate for General Electric has shifted from US$350.45 to about US$404.90 per share, which is a meaningful reset in how analysts are framing the stock. Recent research following Q2 results and updated guidance links this higher figure to stronger views on GE Aerospace execution, service demand and the durability of the current order and backlog profile. As you read on, you will see how to track this evolving narrative and what it may mean for your own view on General...",
        "The designation and contract mark advancement of the program designed to provide small, low-cost, high-performance engines for use in cruise missiles, collaborative combat-type aircraft, and other uncrewed aerial",
        "GE's defense momentum continues as rising demand, major contracts and a strong project pipeline lift revenues, orders and profit.",
        "Despite record revenue, GE Aerospace is falling further behind on orders. Spare parts delinquencies, a measure of shipments delayed by material shortages, grew last quarter. This is not a sign of weakness, but of demand so intense the company's industrial base cannot keep pace.",

        # CAT
        "Caterpillar (NYSE:CAT) has outperformed the market over the past 5 years by 21.71% on an annualized basis producing an average annual return of 33.53%. Currently, Caterpillar has a market capitalization of $409.17",
        "Investment will focus on making training more accessible, defining what skills are needed for future jobs and connecting individuals to careers in modern manufacturingThe Academies of Central Arkansas, University of",

        # BA
        "https://www.state.gov/releases/bureau-of-political-military-affairs/2026/08/qatar-kc-46a-aerial-refueling-aircraft/",

        # HON
        "Honeywell Technologies (NASDAQ:HON) announced the appointment of Billal Hammoud as President and CEO of Process Technology, a component of the company’s Process Automation &amp; Technology reportable business segment,",
        "A significant share of the company's 3,000 suppliers underperformed in the first half of the year, President and CEO James Currier said.",
        "RBC Capital  analyst Deane Dray   maintains Honeywell Intl (NASDAQ:HON) with a Outperform and lowers the price target from $298 to $293.",
        "Honeywell Technologies faces near-term pressure from weak demand, rising costs and debt, but automation growth and a $20B backlog offer support.",

        # UPS
        "United Parcel Service (UPS) is rated HOLD due to ongoing core U.S. volume weakness and margins below historical levels, despite recent topline growth.",
        "UPS is targeting about $3 billion in 2026 network savings as stronger pricing, higher cash flow and cost cuts support margins despite weaker package volumes.",
        "Shippers including FedEx and UPS that acted as customs brokers for imported packages and received tariff refunds from the U.S. government have started to pass on those refunds to the customers that originally paid the tariffs."
    ],

    expected_ranking = ["GE", "CAT", "BA", "HON", "UPS"],
    ),

    # mixed_004   JNJ MRK ABBV PFE BMY
    #   "Rank Johnson & Johnson, Merck, AbbVie, Pfizer and Bristol Myers
    #    Squibb using valuation, revenue growth, current market
    #    performance and sentiment from recent coverage. Explain the
    #    evidence behind the ranking."
    #
    #   Merck's contradictory analyst actions and Bristol Myers'
    #   approval-plus-lawsuit make the sentiment branch do real work
    #   against otherwise stable metrics.
    #
    EvalQuestion(
        question_id="mixed_004",
        question=(
            "Rank Johnson & Johnson, Merck, AbbVie, Pfizer and Bristol "
            "Myers Squibb using valuation, revenue growth, current market "
            "performance and sentiment from recent coverage. Explain the "
            "evidence behind the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],
        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('JNJ', 'MRK', 'ABBV', 'PFE', 'BMY') "
            "ORDER BY fm.revenue_growth DESC"
        ),
        expected_sql_result=[
            {"ticker": "ABBV", "name": "AbbVie Inc.", "pe_ratio": 73.96327, "eps": 3.54, "revenue_growth": 0.102},
            {"ticker": "JNJ", "name": "Johnson & Johnson", "pe_ratio": 31.053427, "eps": 8.61, "revenue_growth": 0.066},
            {"ticker": "BMY", "name": "Bristol-Myers Squibb Company", "pe_ratio": 14.420705, "eps": 4.54, "revenue_growth": 0.057},
            {"ticker": "MRK", "name": "Merck & Company, Inc.", "pe_ratio": 119.192, "eps": 1.25, "revenue_growth": 0.051},
            {"ticker": "PFE", "name": "Pfizer, Inc.", "pe_ratio": 36.565792, "eps": 0.76, "revenue_growth": 0.026},
        ],
        sql_order_requirement="none",
        reference_answer=(
            "AbbVie Inc. (ABBV) shows stellar operational execution, highest "
            "revenue growth in the cohort, and strong coverage momentum. AbbVie "
            "exceeded quarterly earnings expectations, while regulatory review "
            "for a new subcutaneous option for Skyrizi in Crohn's disease drives "
            "potential breakout sentiment alongside a $300 analyst price "
            "target.\n\nMerck & Co. (MRK) is supported by strong oncology momentum "
            "and top-tier analyst upgrades. Morgan Stanley upgraded MRK to "
            "Overweight with a $179 price target following positive Phase 3 "
            "results for its personalized melanoma vaccine combined with "
            "Keytruda, alongside BMO raising its target to $170, despite minor "
            "broker downgrades.\n\nJohnson & Johnson (JNJ) offers steady defensive "
            "characteristics. JNJ beat Q2 expectations, raised fiscal 2026 EPS "
            "guidance, and maintains a Moderate Buy consensus with a $268.22 "
            "target.\n\nPfizer Inc. (PFE) shows signs of stabilization. Pfizer "
            "beat Q2 expectations, progresses its obesity pipeline, and "
            "established a settlement program covering ~5,000 Depo-Provera "
            "lawsuit claims to reduce legal uncertainty.\n\nBristol Myers Squibb "
            "(BMY) secured accelerated FDA approval for its novel CELMoD therapy "
            "ZENBEXUS in multiple myeloma, but faces overhangs from a revived "
            "Celgene shareholder lawsuit and cooling AstraZeneca merger rumors."
        ),
        reference_contexts=[
            # ABBV
            "Vest Financial LLC reduced its stake in AbbVie Inc. by 1.4% in the second quarter, selling 3,946 shares and retaining 268,319 shares valued at approximately $67.5 million. Other institutional investors have also adjusted their positions, and institutional ownership collectively stands at 70.23% of ABBV. Additionally, AbbVie reported strong quarterly earnings, exceeding expectations with $3.65 EPS and $16.99 billion in revenue, while maintaining a $1.73 quarterly dividend.",
            "AbbVie recently completed a $9 billion debt offering consisting of unsecured senior notes maturing between 2028 and 2066. The primary purpose of this debt issuance is to finance its acquisition of Apogee Therapeutics, with a provision for redemption if the deal falls through. Analysts currently rate ABBV stock as a Buy with a $300 price target, though TipRanks' AI Analyst, Spark, identifies it as Neutral due to strong cash generation offset by high debt.",
            "AbbVie (ABBV) stock is trading at the top of its 52-week range, driven by the potential for a new subcutaneous induction option for its immunology drug SKYRIZI in Crohn's disease, which is currently under regulatory review. This dosing change is expected to accelerate SKYRIZI sales, a drug that already accounts for nearly a third of AbbVie's guided revenue and has seen its sales forecast raised twice this year.",

            # MRK
            "BMO Capital Markets raised Merck & Co., Inc.'s (NYSE:MRK) price target to $170.00 from $142.00, maintaining an \"outperform\" rating with a potential upside of 12.49%. This comes amidst mixed analyst sentiment, although the consensus rating remains \"Moderate Buy\" with an average target of $142.10. The company's recent quarterly results surpassed expectations, and its Keytruda-personalized cancer vaccine program shows promise, despite significant insider stock sales.",
            "Morgan Stanley upgraded Merck & Co., Inc. (NYSE:MRK) from \"equal weight\" to \"overweight\" and increased its price target from $116 to $179, suggesting a 17.6% upside. This upgrade follows positive late-stage results for Merck's personalized melanoma vaccine combined with Keytruda, which strengthens its oncology pipeline.",
            "Jefferies Financial Group has downgraded Merck & Co., Inc. (NYSE:MRK) from a \"strong-buy\" to a \"hold\" rating, despite a broader analyst consensus of \"moderate buy.\" The downgrade follows Merck's recent positive Phase 3 results for a personalized melanoma vaccine combined with Keytruda, which presents a significant growth opportunity, but also comes with regulatory and patent expiry risks.",

            # JNJ
            "Vest Financial LLC significantly reduced its stake in Johnson & Johnson (JNJ) by selling 103,567 shares in the second quarter, although it still retains a substantial holding worth approximately $65.8 million. This comes as Johnson & Johnson reported strong quarterly results, exceeding revenue and EPS expectations, and increased its fiscal 2026 EPS guidance. Analysts generally maintain a \"Moderate Buy\" rating for JNJ, citing its defensive growth characteristics and consistent dividend increases.",
            "Johnson & Johnson reported strong quarterly earnings, beating expectations with $2.90 EPS and $25.31 billion in revenue, and declared a quarterly dividend of $1.34 per share, while analysts maintain a \"Moderate Buy\" rating with a target price of $268.22.",

            # PFE
            "Janney Montgomery Scott LLC has increased its stake in Pfizer Inc. by 3.4% during the second quarter, bringing its total holdings to 2.41 million shares valued at approximately $58.14 million. Pfizer recently reported strong quarterly earnings of $0.77 per share and revenue of $15.03 billion, surpassing analyst expectations, and declared a quarterly dividend of $0.43 per share.",
            "Pfizer (NYSE:PFE) has established a settlement program aimed at resolving a significant portion of federal lawsuits concerning Depo-Provera intracranial meningioma, potentially covering around 5,000 of over 6,200 pending claims. This confidential agreement is a crucial legal development that could impact Pfizer's litigation reserves, risk profile, and public perception.",

            # BMY
            "Bristol Myers Squibb (NYSE:BMY) today announced that the U.S. Food and Drug Administration (FDA) has approved ZENBEXUS™ (iberdomide) in combination with daratumumabandhyaluronidase-fihj and dexamethasone (ZDd) for the",
            "A unanimous 3-judge panel ruled that UMB Bank had standing to represent former Celgene shareholders despite a procedural error in its appointment"
        ],
        expected_ranking=["ABBV", "MRK", "JNJ", "PFE", "BMY"],
    ),

    # mixed_005   ABT TMO DHR AMGN
    #   "Rank Abbott, Thermo Fisher, Danaher and Amgen on valuation,
    #    revenue growth, current market performance and recent document
    #    sentiment. Explain the evidence behind the order."
    #
    #   Danaher has two chunks — thin enough to state in the answer, not
    #   thin enough to disqualify.
    #
    EvalQuestion(
        question_id="mixed_005",
        question=(
            "Rank Abbott, Thermo Fisher, Danaher and Amgen on valuation, "
            "revenue growth, current market performance and recent document "
            "sentiment. Explain the evidence behind the order."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('ABT', 'TMO', 'DHR', 'AMGN') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "ABT", "name": "Abbott Laboratories", "pe_ratio": 36.93851, "eps": 3.09, "revenue_growth": 0.13},
            {"ticker": "TMO", "name": "Thermo Fisher Scientific Inc", "pe_ratio": 33.757397, "eps": 18.59, "revenue_growth": 0.105},
            {"ticker": "AMGN", "name": "Amgen Inc.", "pe_ratio": 26.93975, "eps": 16.1, "revenue_growth": 0.095},
            {"ticker": "DHR", "name": "Danaher Corporation", "pe_ratio": 38.55536, "eps": 5.6, "revenue_growth": 0.055},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       ABT TMO DHR AMGN --python

        reference_answer = (
        "Amgen Inc. (AMGN) ranks first overall in this healthcare cohort, "
        "followed by Abbott Laboratories (ABT), Thermo Fisher Scientific (TMO), and Danaher Corporation (DHR).\n\n"
        "Amgen Inc. (AMGN) leads the cohort by pairing robust earnings growth and low P/E valuation with strong bullish analyst sentiment. "
        "Analyst price targets for Amgen have been raised significantly across major firms—including Argus Research ($460) and Piper Sandler ($457)—outweighing "
        "the scheduled termination of its research collaboration agreement with TScan Therapeutics.\n\n"
        "Abbott Laboratories (ABT) ranks second, supported by solid medical device and diagnostics fundamentals, a Q2 beat-and-raise, "
        "and a Wolfe Research upgrade to Outperform with a $130 price target, despite insider sales reported by congressional members.\n\n"
        "Thermo Fisher Scientific (TMO) ranks third with positive operational news. Thermo Fisher benefits from biopharma recovery sentiment, "
        "the completed $1.1B sale of its microbiology unit to Astorg, and strategic expansion into precision medicine platforms.\n\n"
        "Danaher Corporation (DHR) ranks fourth. While Danaher points toward a 2027 growth reacceleration, near-term softness in its "
        "bioprocessing unit and higher valuation multiples keep its relative ranking constrained compared to peers."
    ),

    reference_contexts = [
        # AMGN
        "Argus Research  analyst Jasper Hellweg   maintains Amgen (NASDAQ:AMGN) with a Buy and raises the price target from $375 to $460.",
        "Piper Sandler  analyst David Amsellem   maintains Amgen (NASDAQ:AMGN) with a Overweight and raises the price target from $427 to $457.",
        "On August 12, 2026, TScan Therapeutics, Inc. (the "
        "&#34;Company&#34;) received notice from Amgen Inc. "
        "(&#34;Amgen&#34;) of its election to terminate, in its "
        "entirety, the Research Collaboration and License Agreement,",

        # ABT
        "Abbott stays a buy after Q2 beat/raise; Exact Sciences boosts growth. Click for more on ABT stock.",
        "An official report on August 18, 2026 reveals Representative Rick Allen&#39;s recent sale of Abbott Laboratories (NYSE:ABT) stock, valued between $15,001 and $50,000. The transaction took place on July 14, 2026, as per",
        "Wolfe Research  analyst Mike Polark   upgrades Abbott Laboratories (NYSE:ABT) from Peer Perform to Outperform and announces $130 price target.",

        # TMO
        "Thermo Fisher Scientific: Biopharma Recovery And Share Gains Support The Upside",
        "European private equity firm Astorg will run the business as an independent diagnostics company, led by former PerkinElmer CEO Dirk Bontridder.",

        # DHR
        "When biopharmaceutical suppliers report earnings, ripples move fast across the sector. On July 21, Danaher Corporation (NYSE:DHR) reported its Q2 2026 results. While the life sciences giant continues to lead in financial scale, its bioprocessing unit missed expectations, signaling continued softness in broader biopharma demand. The news hit European supplier Sartorius AG, which traded lower […]",
        "Danaher: 2027 Growth Reacceleration Should Drive Upside"
    ],

    expected_ranking = ["AMGN", "ABT", "TMO", "DHR"],
    ),

    # mixed_006   JPM BAC WFC C GS
    #   "Rank JPMorgan, Bank of America, Wells Fargo, Citigroup and
    #    Goldman Sachs using valuation, revenue growth, current market
    #    performance and sentiment from recent documents. Explain the
    #    ranking."
    #
    #   Coverage is macro-heavy, so this ranking leans on SQL and market
    #   data more than the other cohorts do. Say so in the answer.
    #
    EvalQuestion(
        question_id="mixed_006",
        question=(
            "Rank JPMorgan, Bank of America, Wells Fargo, Citigroup and "
            "Goldman Sachs using valuation, revenue growth, current market "
            "performance and sentiment from recent documents. Explain the "
            "ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('JPM', 'BAC', 'WFC', 'C', 'GS') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "GS", "name": "Goldman Sachs Group, Inc. (The)", "pe_ratio": 15.469354, "eps": 64.77, "revenue_growth": 0.425},
            {"ticker": "JPM", "name": "JP Morgan Chase & Co.", "pe_ratio": 15.068581, "eps": 23.33, "revenue_growth": 0.304},
            {"ticker": "BAC", "name": "Bank of America Corporation", "pe_ratio": 14.286374, "eps": 4.33, "revenue_growth": 0.168},
            {"ticker": "C", "name": "Citigroup Inc.", "pe_ratio": 13.973061, "eps": 9.28, "revenue_growth": 0.155},
            {"ticker": "WFC", "name": "Wells Fargo & Company", "pe_ratio": 12.165697, "eps": 6.88, "revenue_growth": 0.095},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       JPM BAC WFC C GS --python

        reference_answer = (
        "Goldman Sachs (GS) ranks first overall in this banking cohort, "
        "followed by JPMorgan Chase (JPM), Bank of America (BAC), Citigroup (C), and Wells Fargo (WFC).\n\n"
        "Goldman Sachs (GS) leads the cohort with top-tier revenue growth and outstanding coverage sentiment. "
        "Goldman reported strong quarterly earnings beating analyst estimates, increased its quarterly dividend to $5.00, "
        "and maintains a Moderate Buy rating with a $1,062.86 price target alongside major institutional stake additions.\n\n"
        "JPMorgan Chase (JPM) ranks second, backed by strong long-term market outperformance (18.46% 5-year annualized return, "
        "beating the market by 6.71%) and analyst backing pointing toward a potential $1T market capitalization, despite ending its relationship with Polymarket.\n\n"
        "Bank of America (BAC) ranks third, delivering robust Q2 results with net income up 27% and diluted EPS up 34%, "
        "though analyst Hold ratings reflect full terminal valuation assumptions and Berkshire Hathaway trimmed its stake.\n\n"
        "Citigroup (C) ranks fourth, supported by operational technology adoption—including Ant International's upgraded forex AI tool—despite "
        "broader market adjustments in energy and equipment coverage.\n\n"
        "Wells Fargo (WFC) ranks fifth. While WFC trades at a 26.5% discount to estimated intrinsic value under the Excess Returns model, "
        "persistent workforce layoffs in West Des Moines and ongoing regulatory pressure in its mortgage division keep its relative outlook weighted."
    ),

    reference_contexts = [
        # GS
        "Lynch Asset Management Inc. has acquired a new stake in The Goldman Sachs Group, Inc. worth approximately $10.66 million, making it their ninth-largest holding. This investment comes as Goldman Sachs reports strong quarterly earnings, beating analyst estimates, and increasing its quarterly dividend. The company maintains a \"Moderate Buy\" consensus rating from analysts, with institutional investors owning a significant portion of its stock.",
        "M3 Wealth Management LLC acquired 3,508 shares of The Goldman Sachs Group, Inc. (GS) worth approximately $3.55 million, making it their 17th-largest holding. Goldman Sachs recently reported strong quarterly earnings, surpassing analyst estimates, and increased its quarterly dividend to $5.00 per share, yielding 2.0%. Analysts maintain a \"Moderate Buy\" rating with an average price target of $1,062.86.",

        # JPM
        "JPMorgan Chase (NYSE:JPM) has outperformed the market over the past 5 years by 6.71% on an annualized basis producing an average annual return of 18.46%. Currently, JPMorgan Chase has a market capitalization of $959.71",
        "Wells Fargo says JPMorgan could become the first $1 trillion bank, with potential to double its market cap within 7-8 years.",
        "JPMorgan reportedly ended its banking relationship with Polymarket over regulatory concerns, while still eyeing a potential IPO role.",

        # BAC
        "Bank of America delivered robust Q2 results, with net income up 27% and diluted EPS up 34%, driven by broad revenue growth. Read why BAC stock is a Hold.",
        "Berkshire Hathawayâs Q2 2026 13F: portfolio hits ~$299B as "
        "Buffett adds Alphabet & trims BACâsee top holdings, key "
        "moves, and buyback details now.",

        # C
        "Banks including Barclays, Citi, Deutsche Bank, and Standard Chartered have adopted an upgraded foreign exchange AI tool developed by Ant International. Ant International is an overseas affiliate and spin-out of Ant Group. This adoption signifies a move by major financial institutions to leverage advanced AI in forex operations.",

        # WFC
        "Wells Fargo (WFC) stock, despite a 122.1% return over the past three years, continues to trade below its estimated intrinsic value based on the Excess Returns model and earnings multiples. While recent investor interest in bank stocks has narrowed the valuation gap, the stock screens as undervalued by 26.5% according to the Excess Returns analysis and also appears undervalued based on its P/E multiple compared to a tailored Fair Ratio benchmark.",
        "Wells Fargo announced another round of layoffs, cutting 14 jobs at its Jordan Creek campus in West Des Moines, bringing the total for the year to 322 in the Des Moines metro. Since April 2022, the bank has eliminated 1,619 jobs in the area through 103 rounds of layoffs, as CEO Charlie Scharf continues to slim down the workforce amid industry changes."
    ],

    expected_ranking = ["GS", "JPM", "BAC", "C", "WFC"],
    ),

    # mixed_007   AXP MA PYPL V
    #   "Rank American Express, Mastercard, PayPal and Visa on valuation,
    #    revenue growth, current market performance and the sentiment of
    #    recent coverage, and explain the evidence behind each placement."
    #
    #   Visa has one chunk. Say so rather than ranking it on nothing.
    #
    EvalQuestion(
        question_id="mixed_007",
        question=(
            "Rank American Express, Mastercard, PayPal and Visa on "
            "valuation, revenue growth, current market performance and the "
            "sentiment of recent coverage, and explain the evidence behind "
            "each placement."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],
        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('AXP', 'MA', 'PYPL', 'V') "
            "ORDER BY fm.revenue_growth DESC"
        ),
        expected_sql_result=[
            {"ticker": "V", "name": "Visa Inc.", "pe_ratio": 31.17903, "eps": 11.73, "revenue_growth": 0.144},
            {"ticker": "MA", "name": "Mastercard Incorporated", "pe_ratio": 31.547552, "eps": 18.19, "revenue_growth": 0.141},
            {"ticker": "AXP", "name": "American Express Company", "pe_ratio": 20.081867, "eps": 16.49, "revenue_growth": 0.128},
            {"ticker": "PYPL", "name": "PayPal Holdings, Inc.", "pe_ratio": 11.7769375, "eps": 5.29, "revenue_growth": 0.048},
        ],
        sql_order_requirement="none",
        reference_answer=(
            "Mastercard (MA) pairs premium growth with strong bullish sentiment. "
            "Mastercard is supported by solid technical setups, new strategic "
            "partnerships (including cross-border stablecoin payments and "
            "expanded co-branded card benefits), and major institutional "
            "accumulation from Pershing Square.\n\nAmerican Express (AXP) is "
            "backed by strong Q2 earnings beating EPS estimates ($4.53 EPS) and "
            "positive revenue growth, though tempered by legal headwinds after "
            "losing a federal appellate court ruling on merchant antitrust "
            "arbitration.\n\nPayPal (PYPL) expands its payment volume through new "
            "higher-education tuition integrations for PayPal and Venmo and "
            "draws speculative takeover interest, though ongoing competitive "
            "pressure keeps analyst ratings at Hold.\n\nVisa (V) has no usable "
            "recent company document coverage in the corpus, preventing "
            "qualitative sentiment verification."
        ),
        reference_contexts=[
            # MA
            "Pershing Square initiated positions in Visa and Mastercard, citing their dominant network status. Read the full analysis for more details.",
            "In recent days, Mastercard’s Eastern Europe, Middle East and Africa unit named 20-year company veteran Yasemin Bedir as its next president effective September 1, 2026, while the company also expanded collaborations ranging from crypto-compliant cross-border stablecoin payments with Borderless.xyz to merchant cloud services with Fiserv and enhanced co-branded card benefits with American Airlines and Citi. At the same time, Bill Ackman’s Pershing Square has disclosed a new position in...",

            # AXP
            "The U.S. Court of Appeals for the First Circuit has affirmed a lower court's decision, denying American Express's attempt to force antitrust claims from thousands of merchants into arbitration. The merchants allege that American Express's anti-steering and non-discrimination provisions violate federal antitrust law.",
            "Asahi Life Asset Management CO. LTD. has acquired 7,546 shares of American Express Company (NYSE:AXP) valued at approximately $2.55 million, making it their 16th-largest portfolio holding. American Express reported strong Q2 earnings with EPS of $4.53 and revenue up 10% year-over-year, reaffirming its FY 2026 EPS guidance. Analyst sentiment remains largely positive, with a \"Moderate Buy\" consensus rating and an average price target of $373.32, despite a recent downgrade from one firm.",

            # PYPL
            "PayPal (Nasdaq: PYPL) today announced new integrations with three of the nation's leading education payment platforms, Illumia, Nelnet Campus Commerce, and TouchNet, that give students and their families the option to pay tuition and fees directly with PayPal or Venmo. These integrations are live at schools across the nation, including Bellarmine University, Butler University, Kansas State University, Michigan State University, and Texas Tech University, with more institutions expected to join t",
            "Truist Securities  analyst Matthew Coad   maintains PayPal Holdings (NASDAQ:PYPL) with a Hold and raises the price target from $59 to $62."
        ],
        expected_ranking=["MA", "AXP", "PYPL", "V"],
    ),

    # mixed_008   BLK SCHW MS
    #   "Rank BlackRock, Charles Schwab and Morgan Stanley using
    #    valuation, revenue growth, current market performance and
    #    sentiment from recent company documents. Explain the ranking."
    #
    #   Nearly all documents are filings and house research — the
    #   sentiment branch contributes least here, which is the point of
    #   including it.
    #
    EvalQuestion(
        question_id="mixed_008",
        question=(
            "Rank BlackRock, Charles Schwab and Morgan Stanley using "
            "valuation, revenue growth, current market performance and "
            "sentiment from recent company documents. Explain the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('BLK', 'SCHW', 'MS') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "BLK", "name": "BlackRock, Inc.", "pe_ratio": 27.320707, "eps": 41.72, "revenue_growth": 0.306},
            {"ticker": "MS", "name": "Morgan Stanley", "pe_ratio": 16.756866, "eps": 12.38, "revenue_growth": 0.28},
            {"ticker": "SCHW", "name": "The Charles Schwab Corporation", "pe_ratio": 19.99818, "eps": 5.49, "revenue_growth": 0.209},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       BLK SCHW MS --python

        reference_answer = (
        "The Charles Schwab Corporation (SCHW) ranks first overall in this asset management and brokerage cohort, "
        "followed by Morgan Stanley (MS) and BlackRock, Inc. (BLK).\n\n"
        "The Charles Schwab Corporation (SCHW) leads the cohort by pairing strong fundamental earnings growth with top-tier coverage sentiment. "
        "Schwab reported strong Q2 earnings beating expectations ($1.62 EPS, $7.07B revenue) and trades near 12-month highs with analyst fair value "
        "targets of $125.00, supported by major institutional stake additions including a ~$988M buy by Flossbach Von Storch.\n\n"
        "Morgan Stanley (MS) ranks second, backed by strong research momentum across its wealth and asset management units. "
        "Morgan Stanley's coverage highlights bullish strategic positioning in AI infrastructure energy demand, real estate, and gold market forecasts, "
        "alongside key institutional stake increases by Trian.\n\n"
        "BlackRock, Inc. (BLK) ranks third. While BlackRock demonstrates active strategic execution by lowering its iShares Bitcoin Trust "
        "conversion threshold from $25M to $1M to boost liquidity and expanding European equity holdings in adidas and Commerzbank, its overall document coverage is less earnings-driven."
    ),

    reference_contexts = [
        # SCHW
        "Charles Schwab stock is trading near its 12-month high, supported by strong second-quarter 2026 earnings and an updated fair value estimate of $125.00, which is above its current share price of $110.85. The company reported adjusted earnings of $1.62 per share and revenue of $7.07 billion, both exceeding analyst expectations, with robust net margins and return on equity. Institutional interest and a consistent dividend policy further bolster investor confidence in the stock's valuation.",
        "Great Lakes Advisors LLC recently purchased a new stake of $7.20 million in The Charles Schwab Corporation (NYSE:SCHW) during the second quarter. Other institutional investors like BlackRock and Danske Bank also increased their holdings, with institutional ownership now at 84.38%. Charles Schwab reported strong Q2 earnings, exceeding expectations with $1.62 EPS and $7.07 billion in revenue, and analysts maintain a \"Moderate Buy\" rating with an average price target of $121.17.",
        "Flossbach Von Storch SE has made a significant new investment in The Charles Schwab Corporation, purchasing over 10.7 million shares valued at approximately $987.93 million, making it their sixth-largest holding.",

        # MS
        "Lauren Hochfelder, head of global real assets at Morgan Stanley, suggests that industrial real estate offers an indirect avenue into the artificial intelligence sector. She discusses the current real estate market and how the expanding AI industry is increasingly influencing it. Her insights highlight the evolving relationship between technological advancements and property markets.",
        "Morgan Stanley projects a 38-gigawatt power deficit for U.S. AI data centers between 2026 and 2028, leading developers to seek faster power solutions. The article highlights three industrial stocks—GE Vernova, Eaton, and Vertiv—as key players to bridge this gap. These companies provide essential equipment for power generation, distribution, and cooling, making them critical beneficiaries of the AI infrastructure boom.",

        # BLK
        "BlackRock has significantly lowered the minimum requirement for in-kind conversions of its iShares Bitcoin Trust from $25 million to $1 million. This strategic move aims to broaden accessibility for smaller investors, allowing them to convert shares directly into Bitcoin more easily. The change is expected to increase the trust's liquidity and attract a wider range of participants to BlackRock's Bitcoin investment offerings.",
        "Commerzbank AG has released a notification of major holdings according to Article 40, Section 1 of the WpHG. BlackRock, Inc. has acquired voting rights in Commerzbank, crossing a threshold on August 17, 2026. The new total position for BlackRock is 4.52%, comprising 3.01% voting rights attached to shares and 1.51% through instruments."
    ],

    expected_ranking = ["SCHW", "MS", "BLK"],
    ),

    # mixed_009   DIS GOOGL META NFLX
    #   "Rank the communication services companies on valuation, revenue
    #    growth, current market performance and recent document
    #    sentiment, and explain the evidence behind the order."
    #
    #   Netflix has ten documents against Meta's one, so coverage volume
    #   and coverage quality diverge sharply inside one cohort.
    #
    EvalQuestion(
        question_id="mixed_009",
        question=(
            "Rank the communication services companies on valuation, "
            "revenue growth, current market performance and recent document "
            "sentiment, and explain the evidence behind the order."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('DIS', 'GOOGL', 'META', 'NFLX') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "META", "name": "Meta Platforms, Inc.", "pe_ratio": 20.566315, "eps": 26.54, "revenue_growth": 0.28},
            {"ticker": "GOOGL", "name": "Alphabet Inc.", "pe_ratio": 17.101908, "eps": 19.92, "revenue_growth": 0.242},
            {"ticker": "NFLX", "name": "Netflix, Inc.", "pe_ratio": 25.201258, "eps": 3.18, "revenue_growth": 0.134},
            {"ticker": "DIS", "name": "Walt Disney Company (The)", "pe_ratio": 22.127836, "eps": 4.85, "revenue_growth": 0.068},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       DIS GOOGL META NFLX --python
        reference_answer = (
        "Netflix, Inc. (NFLX) ranks first overall in this communication services cohort, "
        "followed by Meta Platforms, Inc. (META), Alphabet Inc. (GOOGL), and The Walt Disney Company (DIS).\n\n"
        "Netflix, Inc. (NFLX) leads the cohort by pairing robust subscriber and revenue performance with standout market sentiment. "
        "Netflix is backed by strong long-term market outperformance (23.1% 10-year annualized return), a 4.9% portfolio stake from Pershing Square "
        "signaling double-digit growth, disciplined capital allocation in walking away from Paramount asset bidding, and market leadership support.\n\n"
        "Meta Platforms, Inc. (META) ranks second, exhibiting strong digital advertising scale and market momentum, though document coverage "
        "registers ongoing debate and scrutiny regarding its open-source AI manifesto positioning against established AI competitors.\n\n"
        "Alphabet Inc. (GOOGL) ranks third, maintaining massive search and video ecosystem reach with YouTube, though sentiment is tempered "
        "by aggressive content defense spending to counter Netflix's subscriber expansion efforts and broader mega-cap tech sector volatility.\n\n"
        "The Walt Disney Company (DIS) ranks fourth. Disney faces notable sentiment headwinds from regulatory and legal friction, "
        "highlighted by its First Amendment lawsuit against the FCC alleging retaliatory probes into ABC broadcasting programming."
    ),

    reference_contexts = [
        # NFLX
        "Netflix (NASDAQ:NFLX) has outperformed the market over the past 10 years by 9.62% on an annualized basis producing an average annual return of 23.1%. Currently, Netflix has a market capitalization of $319.23 billion.",
        "Netflix stock climbs after Pershing Square takes a 4.9% portfolio position, signaling double-digit growth and market leadership.",
        "Paramount's motion for a $1.9B bond exposes a balance sheet already in the Altman-Z distress zone. Why Netflix's discipline to walk away looks smarter every week.",

        # META
        "Mark Zuckerberg's \"AI manifesto,\" \"The Future is for Everyone,\" outlines a vision of democratized AI and personal superintelligence agents. However, the article questions whether Meta's past actions and current capabilities align with this ambitious vision, particularly concerning its commitment to open-source principles and its standing in the competitive AI landscape. It suggests that Meta's public stance might be more of a PR move to position itself amidst stronger AI contenders.",

        # GOOGL
        "YouTube is offering millions to popular creators for exclusive video uploads, aiming to prevent them from simultaneously working with Netflix. This strategy includes direct financing of programs and sharing portions of major brand deals. Netflix has been paying YouTubers to cross-post content, seeking to attract younger audiences and expand its subscriber base, which YouTube views as a threat to its viewership and advertising revenue.",

        # DIS
        "Disney's ABC has sued the FCC claiming its investigation and "
        "early broadcast licenses renewal are a \"retaliatory campaign\" "
        "due to its programming.",
        
    ],

    expected_ranking = ["NFLX", "META", "GOOGL", "DIS"],
    ),

    # mixed_010   AMZN HD MCD NKE SBUX TSLA
    #   "Rank the consumer cyclical companies using valuation, revenue
    #    growth, current market performance and sentiment from recent
    #    documents. Explain what each placement rests on."
    #
    #   Six names, and Tesla has one chunk.
    #
    EvalQuestion(
        question_id="mixed_010",
        question=(
            "Rank the consumer cyclical companies using valuation, revenue "
            "growth, current market performance and sentiment from recent "
            "documents. Explain what each placement rests on."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],
        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('AMZN', 'HD', 'MCD', 'NKE', 'SBUX', 'TSLA') "
            "ORDER BY fm.revenue_growth DESC"
        ),
        expected_sql_result=[
            {"ticker": "TSLA", "name": "Tesla, Inc.", "pe_ratio": 316.63303, "eps": 1.09, "revenue_growth": 0.255},
            {"ticker": "AMZN", "name": "Amazon.com, Inc.", "pe_ratio": 20.909164, "eps": 12.44, "revenue_growth": 0.196},
            {"ticker": "HD", "name": "Home Depot, Inc. (The)", "pe_ratio": 23.407278, "eps": 14.29, "revenue_growth": 0.057},
            {"ticker": "MCD", "name": "McDonald's Corporation", "pe_ratio": 21.880487, "eps": 12.3, "revenue_growth": 0.037},
            {"ticker": "NKE", "name": "NIKE, Inc.", "pe_ratio": 19.14762, "eps": 2.1, "revenue_growth": -0.011},
            {"ticker": "SBUX", "name": "Starbucks Corporation", "pe_ratio": 60.109825, "eps": 1.73, "revenue_growth": -0.014},
        ],
        sql_order_requirement="none",
        reference_answer=(
            "Amazon.com, Inc. (AMZN) shows strong long-term total returns and "
            "robust operational execution, highlighted by winning major "
            "enterprise contracts such as Delta Air Lines' satellite WiFi "
            "partnership.\n\nHome Depot, Inc. (HD) delivers resilient Q2 "
            "operational performance with solid revenue growth, digital sales "
            "momentum, and bullish analyst price target revisions across major "
            "brokers.\n\nMcDonald's Corporation (MCD) is taking proactive menu "
            "innovation steps—such as introducing Red Bull beverage offerings "
            "and expanding its drink menu—to revitalize store traffic and "
            "support growth.\n\nStarbucks Corporation (SBUX) offers a solid "
            "historical compounder profile, but faces operational headwinds, "
            "including corporate workforce restructuring layoffs and "
            "international sales disruptions in Korea.\n\nTesla, Inc. (TSLA) leads "
            "the cohort in raw revenue growth, but carries an elevated P/E "
            "multiple and share price pressure from heavy AI infrastructure "
            "capital-spending demands.\n\nNIKE, Inc. (NKE) is heavily weighted "
            "down by negative revenue growth, a severe drawdown from its peak, "
            "erasing $200B in market capitalization, and facing technical "
            "breakdown warnings."
        ),
        reference_contexts=[
            # AMZN
            "This article highlights the significant returns an investment in Amazon.com stock would have yielded over 15 years. An initial investment of $1,000 in AMZN 15 years ago would now be worth over $27,000, demonstrating the power of compounded returns. Amazon.com has outperformed the market with an average annual return of 24.36% over this period.",
            "Delta Air Lines chose Amazon's satellite WiFi over Starlink for its inflight connectivity, a decision Elon Musk claims will lead to passenger losses. Delta's CEO defends the choice, citing brand integration, while Musk points to passengers switching airlines. Other airlines, however, are adopting Starlink, raising concerns about Delta's competitive position if it doesn't offer comparable WiFi.",

            # HD
            "Home Depot delivered a strong Q2 2026 with 5.7% revenue growth and solid digital sales momentum but remains rangebound. Click here for this HD stock update.",
            "Mizuho  analyst David Bellinger   maintains Home Depot (NYSE:HD) with a Outperform and raises the price target from $385 to $390.",

            # MCD
            "McDonald's (MCD) officially added energy drinks to its menu for the first time today with the debut of its new Red Bull Dragonberry Energizer.",

            # SBUX
            "Starbucks (NASDAQ:SBUX) has outperformed the market over the past 20 years by 1.11% on an annualized basis producing an average annual return of 10.45%. Currently, Starbucks has a market capitalization of $125.56",
            "https://www.bloomberg.com/news/articles/2026-08-20/starbucks-sheds-more-than-100-jobs-as-it-wraps-up-restructuring",
            "Starbucks Korea posted its first quarterly loss since it started operations 27 years ago after a marketing debacle triggered a boycott, criticism from President Lee Jae Myung, and a police raid of its corporate offices.",

            # TSLA
            "Ford shares dropped 4% after a rally based on unconfirmed Bronco product reports faded, while General Motors gained 1%, indicating a company-specific reversal for Ford rather than a sector trend. Tesla also slipped 2% due to unrelated AI infrastructure capital-spending pressures. Investors are advised to exercise patience with Ford and monitor its upcoming Bronco recall notification on August 24.",

            # NKE
            "Nike stock has erased $200B in market cap since 2021. Read why Arvy&#39;s CIO warns NKE faces a severe &#39;Stage 4&#39; technical decline."
        ],
        expected_ranking=["AMZN", "HD", "MCD", "SBUX", "TSLA", "NKE"],
    ),

    # mixed_011   AAPL ADBE AMD CRM INTC MSFT NVDA
    #   "Rank the technology sector companies on valuation, revenue
    #    growth, current market performance and the sentiment of their
    #    recent documents, and explain the ranking."
    #
    #   The largest cohort in the set, and the one most likely to expose a
    #   truncation or ordering bug.
    #
    EvalQuestion(
        question_id="mixed_011",
        question=(
            "Rank the technology sector companies on valuation, revenue "
            "growth, current market performance and the sentiment of their "
            "recent documents, and explain the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('AAPL', 'ADBE', 'AMD', 'CRM', 'INTC', 'MSFT', 'NVDA') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 33.20827, "eps": 6.53, "revenue_growth": 0.852},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "pe_ratio": 119.75893, "eps": 3.92, "revenue_growth": 0.501},
            {"ticker": "INTC", "name": "Intel Corporation", "pe_ratio": None, "eps": -2.09, "revenue_growth": 0.254},
            {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 26.77518, "eps": 17.97, "revenue_growth": 0.177},
            {"ticker": "AAPL", "name": "Apple Inc.", "pe_ratio": 35.74053, "eps": 8.71, "revenue_growth": 0.164},
            {"ticker": "CRM", "name": "Salesforce, Inc.", "pe_ratio": 23.776619, "eps": 8.64, "revenue_growth": 0.133},
            {"ticker": "ADBE", "name": "Adobe Inc.", "pe_ratio": 15.564322, "eps": 17.49, "revenue_growth": 0.127},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       AAPL ADBE AMD CRM INTC MSFT NVDA --python

        reference_answer = (
        "NVIDIA Corporation (NVDA) ranks first overall in this technology sector cohort, "
        "followed by Microsoft Corporation (MSFT), Salesforce, Inc. (CRM), Advanced Micro Devices, Inc. (AMD), "
        "Apple Inc. (AAPL), Intel Corporation (INTC), and Adobe Inc. (ADBE).\n\n"
        "NVIDIA Corporation (NVDA) leads the cohort through unparalleled market demand and massive long-term contract momentum. "
        "NVIDIA is backed by multibillion-dollar cloud provider supply deals (including CoreWeave) and long-term lease commitments "
        "totaling up to $50B for Hut 8's Texas data centers to secure GPU infrastructure.\n\n"
        "Microsoft Corporation (MSFT) ranks second, maintaining a dominant market capitalization ($3.60T) and leading market position in the AI supremacy race "
        "alongside enterprise cloud expansion.\n\n"
        "Salesforce, Inc. (CRM) ranks third, demonstrating strong software innovation and revenue execution. "
        "Salesforce's document coverage highlights new Agentforce and Data Cloud ARR momentum, positive earnings expectations with Oppenheimer setting a $250 price target, "
        "and collaborative software launches like Slack Code.\n\n"
        "Advanced Micro Devices, Inc. (AMD) ranks fourth. AMD benefits from strong Q2 performance and institutional stake increases "
        "(such as Wyoming's 87.9% position expansion), though high valuation multiples and insider sales temper its top-tier placement.\n\n"
        "Apple Inc. (AAPL) ranks fifth. Apple maintains solid market resilience and strong iPhone ecosystem cash flows, though near-term sentiment "
        "is affected by memory chip price inflation and institutional position trims.\n\n"
        "Intel Corporation (INTC) ranks sixth. Intel receives strong backing from SoftBank (representing 67% of its U.S. portfolio value), "
        "but dilution from share offerings and ongoing execution risks in its foundry roadmap restrict its relative standing.\n\n"
        "Adobe Inc. (ADBE) ranks seventh. While Adobe passes value screens with high margins and strong FCF generation, persistent market concerns "
        "over AI disruption and flat ARR growth keep its rating constrained across major brokers."
    ),

    reference_contexts = [
        # NVDA
        "CoreWeave Inc. has secured a multiyear, multibillion-dollar agreement with Hudson River Trading, granting Hudson River access to Nvidia's Vera Rubin and B200 AI systems. This deal highlights Wall Street's increasing demand for Nvidia's advanced AI chips for tasks like training trading models and analyzing data. CoreWeave has been raising prices for its AI cloud services, driven by this high demand and its early validation of Nvidia's new platforms.",
        "Hut 8 Corp. (HUT) stock is experiencing a significant surge due to massive long-term AI deals with Nvidia, repositioning the company from a crypto miner to a power-first AI infrastructure operator. These deals, reportedly totaling up to $50 billion over 30 years for its Texas data centers, have led to bullish upgrades and higher price targets from numerous Wall Street firms.",

        # MSFT
        "Meta's market capitalization of $1.39 trillion significantly lags behind Amazon ($2.87 trillion), Microsoft ($3.60 trillion), and Alphabet ($4.19 trillion) in the AI race, despite CEO Mark Zuckerberg's 14-page AI manifesto. Even private AI rival Anthropic is nearing or surpassing Meta's valuation, highlighting investors' diminished view of Meta's social media business and AI strategy compared to its tech giant peers.",

        # CRM
        "Salesforce announces Slack Code, a new feature designed to "
        "bring AI-powered coding agents and software development into "
        "a collaborative, multiplayer environment within Slack. This "
        "allows teams to work with agents like Claude Code, GitHub "
        "Copilot, and ChatGPT directly in dedicated \"code channels\" "
        "where they can write, review, and ship code together.",
        "Oppenheimer has reiterated an Outperform rating on Salesforce (NYSE:CRM) with a $250 price target, anticipating favorable second-quarter earnings. The firm believes Salesforce is currently undervalued and expects upside to consensus estimates, driven by strong new Agentforce and Data Cloud annual recurring revenue.",

        # AMD
        "The State of Wyoming significantly increased its holdings in Advanced Micro Devices (AMD) by 87.9% in Q2, purchasing an additional 2,540 shares to bring its total to 5,431 shares valued at $3.16 million. Institutional investors now own 71.34% of AMD, with many funds increasing their stakes. Despite strong Q2 results, a \"Moderate Buy\" consensus from analysts, and a target price of $546.87, the stock faces risks due to high valuation and recent insider sales.",

        # AAPL
        "Apple stock (AAPL) stays resilient after a 10% correction. AAPL faces margin pressure from a historic memory price upcycle. See more details here.",
        "Viking Global&#39;s Andreas Halvorsen shifts gears in Q2, making an $817M bet on Ferrari while slashing Tesla by 78% and dumping Apple.",

        # INTC
        "SoftBank Group's latest 13F filing reveals that Intel (INTC) now constitutes 67% of its U.S. stock portfolio, valued at $12.1 billion as of June 30. However, this high concentration is due to Intel's stock nearly tripling in the last quarter, not new purchases by Masayoshi Son, as SoftBank held the exact same number of shares.",
        "The article notes that while Intel's business performance is improving, the stock's valuation still appears expensive, especially given its recent price drop and the dilution from Intel's own share offering.",

        # ADBE
        "Adobe bottomed after AI-driven fears and is now trading at highly attractive valuations with strong growth prospects. Read why ADBE stock is a Strong Buy.",
        "Adobe downgraded to Strong Sell despite a 30% rebound: AI "
        "disruption risk persists, ARR growth is flat, and freemium "
        "isnât lifting revenue. Click for more on ADBE stock."
    ],

    expected_ranking = ["NVDA", "MSFT", "CRM", "AMD", "AAPL", "INTC", "ADBE"],
    ),

    # mixed_012   AMZN CRM GOOGL MSFT
    #   "Rank the cloud computing companies using valuation, revenue
    #    growth, current market performance and sentiment from recent
    #    company documents. Explain the evidence behind the ranking."
    #
    #   A theme cohort resolved through company_themes rather than a
    #   ticker list in the question, like mixed_001 but a different theme.
    #
    EvalQuestion(
        question_id="mixed_012",
        question=(
            "Rank the cloud computing companies using valuation, revenue "
            "growth, current market performance and sentiment from recent "
            "company documents. Explain the evidence behind the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('AMZN', 'CRM', 'GOOGL', 'MSFT') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "GOOGL", "name": "Alphabet Inc.", "pe_ratio": 17.101908, "eps": 19.92, "revenue_growth": 0.242},
            {"ticker": "AMZN", "name": "Amazon.com, Inc.", "pe_ratio": 20.909164, "eps": 12.44, "revenue_growth": 0.196},
            {"ticker": "MSFT", "name": "Microsoft Corporation", "pe_ratio": 26.77518, "eps": 17.97, "revenue_growth": 0.177},
            {"ticker": "CRM", "name": "Salesforce, Inc.", "pe_ratio": 23.776619, "eps": 8.64, "revenue_growth": 0.133},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       AMZN CRM GOOGL MSFT --python

        reference_answer = (
        "Amazon.com, Inc. (AMZN) shows market-leading long-term total "
        "returns (24.36% 15-year average annual return) and strong cloud "
        "enterprise momentum through AWS, winning major corporate "
        "infrastructure and inflight connectivity deals like Delta Air "
        "Lines.\n\nMicrosoft Corporation (MSFT) holds a dominant $3.60T market "
        "capitalization and leading position in the enterprise AI and cloud "
        "supremacy battle through Azure infrastructure scaling.\n\nSalesforce, "
        "Inc. (CRM) demonstrates accelerated software and cloud application "
        "growth. Salesforce is backed by strong Agentforce and Data Cloud "
        "ARR momentum, positive Q2 earnings expectations with Oppenheimer "
        "setting a $250 price target, and collaborative software launches "
        "like Slack Code.\n\nAlphabet Inc. (GOOGL): Google Cloud and YouTube "
        "maintain massive ecosystem reach, though Alphabet is constrained by "
        "broader mega-cap tech ETF pullbacks and high creator defense "
        "spending to protect viewership."
    ),

    reference_contexts = [
        # AMZN
        "This article highlights the significant returns an investment in Amazon.com stock would have yielded over 15 years. An initial investment of $1,000 in AMZN 15 years ago would now be worth over $27,000, demonstrating the power of compounded returns. Amazon.com has outperformed the market with an average annual return of 24.36% over this period.",
        "Delta Air Lines chose Amazon's satellite WiFi over Starlink for its inflight connectivity, a decision Elon Musk claims will lead to passenger losses. Delta's CEO defends the choice, citing brand integration, while Musk points to passengers switching airlines. Other airlines, however, are adopting Starlink, raising concerns about Delta's competitive position if it doesn't offer comparable WiFi.",

        # MSFT
        "Meta's market capitalization of $1.39 trillion significantly lags behind Amazon ($2.87 trillion), Microsoft ($3.60 trillion), and Alphabet ($4.19 trillion) in the AI race, despite CEO Mark Zuckerberg's 14-page AI manifesto. Even private AI rival Anthropic is nearing or surpassing Meta's valuation, highlighting investors' diminished view of Meta's social media business and AI strategy compared to its tech giant peers.",

        # CRM
        "Salesforce announces Slack Code, a new feature designed to "
        "bring AI-powered coding agents and software development into "
        "a collaborative, multiplayer environment within Slack. This "
        "allows teams to work with agents like Claude Code, GitHub "
        "Copilot, and ChatGPT directly in dedicated \"code channels\" "
        "where they can write, review, and ship code together.",
        "Oppenheimer has reiterated an Outperform rating on Salesforce (NYSE:CRM) with a $250 price target, anticipating favorable second-quarter earnings. The firm believes Salesforce is currently undervalued and expects upside to consensus estimates, driven by strong new Agentforce and Data Cloud annual recurring revenue.",

        # GOOGL
        "An exchange-traded fund comprising seven major U.S. tech stocks, the Roundhill Magnificent Seven ETF, experienced a sharp decline on Thursday. Shares of Tesla, Amazon, and Alphabet were notably down, with Tesla suffering the largest loss of over 2%. The ETF's overall slump was recorded at 1.1% according to FactSet data.",
        "YouTube is offering millions to popular creators for exclusive video uploads, aiming to prevent them from simultaneously working with Netflix. This strategy includes direct financing of programs and sharing portions of major brand deals. Netflix has been paying YouTubers to cross-post content, seeking to attract younger audiences and expand its subscriber base, which YouTube views as a threat to its viewership and advertising revenue."
    ],

    expected_ranking = ["AMZN", "MSFT", "CRM", "GOOGL"],
    ),

    # mixed_013   AMD INTC NVDA
    #   "Rank the semiconductor companies on valuation, revenue growth,
    #    current market performance and the sentiment of recent coverage.
    #    Explain the evidence behind the order."
    #
    #   Three names, one with a single document — the smallest cohort
    #   worth ranking. Also a routing test: sentiment_002 asks about the
    #   same cohort and must route SENTIMENT, this one MIXED.
    #
    EvalQuestion(
        question_id="mixed_013",
        question=(
            "Rank the semiconductor companies on valuation, revenue growth, "
            "current market performance and the sentiment of recent "
            "coverage. Explain the evidence behind the order."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('AMD', 'INTC', 'NVDA') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 33.20827, "eps": 6.53, "revenue_growth": 0.852},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "pe_ratio": 119.75893, "eps": 3.92, "revenue_growth": 0.501},
            {"ticker": "INTC", "name": "Intel Corporation", "pe_ratio": None, "eps": -2.09, "revenue_growth": 0.254},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       AMD INTC NVDA --python

        reference_answer = (
    "NVIDIA Corporation (NVDA) ranks first overall in this semiconductor cohort, "
    "followed by Advanced Micro Devices, Inc. (AMD) and Intel Corporation (INTC).\n\n"
    "NVIDIA Corporation (NVDA) leads the group with unmatched market demand and multibillion-dollar cloud commitments. "
    "NVIDIA is backed by massive neocloud supply deals (including CoreWeave's access to Vera Rubin and B200 systems) and "
    "long-term lease agreements totaling up to $50B for Hut 8's Texas data centers to secure GPU infrastructure.\n\n"
    "Advanced Micro Devices, Inc. (AMD) ranks second. AMD demonstrates strong Q2 performance and institutional stake accumulation "
    "(such as Wyoming's 87.9% position expansion) with analyst price targets reaching $546.87, though high valuation multiples and recent insider sales temper its top placement.\n\n"
    "Intel Corporation (INTC) ranks third. While Intel receives strong backing from SoftBank (which holds 67% of its U.S. portfolio value in INTC), "
    "its relative standing is constrained by share dilution from offerings and lingering execution risks in its foundry roadmap."
),

reference_contexts = [
    # NVDA
    "CoreWeave Inc. has secured a multiyear, multibillion-dollar agreement with Hudson River Trading, granting Hudson River access to Nvidia's Vera Rubin and B200 AI systems. This deal highlights Wall Street's increasing demand for Nvidia's advanced AI chips for tasks like training trading models and analyzing data. CoreWeave has been raising prices for its AI cloud services, driven by this high demand and its early validation of Nvidia's new platforms.",
    "Hut 8 Corp. (HUT) stock is experiencing a significant surge due to massive long-term AI deals with Nvidia, repositioning the company from a crypto miner to a power-first AI infrastructure operator. These deals, reportedly totaling up to $50 billion over 30 years for its Texas data centers, have led to bullish upgrades and higher price targets from numerous Wall Street firms.",

    # AMD
    "The State of Wyoming significantly increased its holdings in Advanced Micro Devices (AMD) by 87.9% in Q2, purchasing an additional 2,540 shares to bring its total to 5,431 shares valued at $3.16 million. Institutional investors now own 71.34% of AMD, with many funds increasing their stakes. Despite strong Q2 results, a \"Moderate Buy\" consensus from analysts, and a target price of $546.87, the stock faces risks due to high valuation and recent insider sales.",

    # INTC
    "SoftBank Group's latest 13F filing reveals that Intel (INTC) now constitutes 67% of its U.S. stock portfolio, valued at $12.1 billion as of June 30. However, this high concentration is due to Intel's stock nearly tripling in the last quarter, not new purchases by Masayoshi Son, as SoftBank held the exact same number of shares.",
    "The article notes that while Intel's business performance is improving, the stock's valuation still appears expensive, especially given its recent price drop and the dilution from Intel's own share offering."
],

expected_ranking = ["NVDA", "AMD", "INTC"],
    ),

    # mixed_014   INTC PYPL WFC BAC
    #   "Rank Intel, PayPal, Wells Fargo and Bank of America using
    #    valuation, revenue growth, current market performance and
    #    sentiment from recent documents. Explain the evidence behind the
    #    ranking."
    #
    #   Built so the branches disagree: cheap on the metrics, troubled in
    #   the documents. Whichever way you rank it, say which signal won.
    #
    EvalQuestion(
        question_id="mixed_014",
        question=(
            "Rank Intel, PayPal, Wells Fargo and Bank of America using "
            "valuation, revenue growth, current market performance and "
            "sentiment from recent documents. Explain the evidence behind "
            "the ranking."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('INTC', 'PYPL', 'WFC', 'BAC') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "INTC", "name": "Intel Corporation", "pe_ratio": None, "eps": -2.09, "revenue_growth": 0.254},
            {"ticker": "BAC", "name": "Bank of America Corporation", "pe_ratio": 14.286374, "eps": 4.33, "revenue_growth": 0.168},
            {"ticker": "WFC", "name": "Wells Fargo & Company", "pe_ratio": 12.165697, "eps": 6.88, "revenue_growth": 0.095},
            {"ticker": "PYPL", "name": "PayPal Holdings, Inc.", "pe_ratio": 11.7769375, "eps": 5.29, "revenue_growth": 0.048},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       INTC PYPL WFC BAC --python
      reference_answer = (
    "Bank of America Corporation (BAC) ranks first overall in this evaluation, "
    "followed by Intel Corporation (INTC), Wells Fargo & Company (WFC), and PayPal Holdings, Inc. (PYPL).\n\n"
    "Bank of America Corporation (BAC) leads the cohort by pairing robust earnings growth with solid market performance. "
    "Bank of America delivered strong Q2 results with net income up 27% and diluted EPS up 34%, while outperforming "
    "the broader equity market YTD as credit conditions change.\n\n"
    "Intel Corporation (INTC) ranks second, backed by massive institutional backing with SoftBank holding 67% of its "
    "U.S. equity portfolio in INTC, reflecting confidence in its AI and foundry roadmap despite share dilution from recent offerings.\n\n"
    "Wells Fargo & Company (WFC) ranks third. While WFC trades at a 26.5% discount to estimated intrinsic value under the "
    "Excess Returns model and reported strong Q2 financial results, ongoing workforce layoffs in West Des Moines and regulatory "
    "pressures in its home mortgage division constrain its relative ranking.\n\n"
    "PayPal Holdings, Inc. (PYPL) ranks fourth. Although PayPal expands its addressable payment volume through new higher-education "
    "tuition integrations for PayPal and Venmo and draws speculative takeover interest, analyst sentiment remains neutral with Hold ratings."
),

reference_contexts = [
    # BAC
    "Bank of America delivered robust Q2 results, with net income up 27% and diluted EPS up 34%, driven by broad revenue growth. Read why BAC stock is a Hold.",
    "Bank of America is outperforming the already elevated equity market YTD as credit conditions change. Read more on BAC stock here.",

    # INTC
    "SoftBank Group has made Intel (NasdaqGS: INTC) the largest component of its U.S. equity portfolio, with the stock representing nearly 67% of its disclosed holdings. This significant concentration signals a strong vote of confidence from SoftBank in Intel's AI and foundry roadmap, aligning with Intel's recent strategic shifts and capital raises.",
    "The article notes that while Intel's business performance is improving, the stock's valuation still appears expensive, especially given its recent price drop and the dilution from Intel's own share offering.",

    # WFC
    "Wells Fargo (WFC) stock, despite a 122.1% return over the past three years, continues to trade below its estimated intrinsic value based on the Excess Returns model and earnings multiples. While recent investor interest in bank stocks has narrowed the valuation gap, the stock screens as undervalued by 26.5% according to the Excess Returns analysis and also appears undervalued based on its P/E multiple compared to a tailored Fair Ratio benchmark.",
    "This follows strong second-quarter financial results but reflects ongoing adjustments to market conditions and regulatory pressure, particularly impacting its home mortgage division.",

    # PYPL
    "PayPal (Nasdaq: PYPL) today announced new integrations with three of the nation's leading education payment platforms, Illumia, Nelnet Campus Commerce, and TouchNet, that give students and their families the option to pay tuition and fees directly with PayPal or Venmo. These integrations are live at schools across the nation, including Bellarmine University, Butler University, Kansas State University, Michigan State University, and Texas Tech University, with more institutions expected to join t",
    "Truist Securities  analyst Matthew Coad   maintains PayPal Holdings (NASDAQ:PYPL) with a Hold and raises the price target from $59 to $62."
],

expected_ranking = ["BAC", "INTC", "WFC", "PYPL"],

    ),

    # mixed_015   NVDA AMD CRM ADBE
    #   "Rank NVIDIA, AMD, Salesforce and Adobe on valuation, revenue
    #    growth, current market performance and recent document
    #    sentiment, and explain what drives the order."
    #
    #   The opposite disagreement — strong revenue growth against
    #   expensive multiples and coverage that is mostly about customers.
    EvalQuestion(
        question_id="mixed_015",
        question=(
            "Rank NVIDIA, AMD, Salesforce and Adobe on valuation, revenue "
            "growth, current market performance and recent document "
            "sentiment, and explain what drives the order."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=["planner", "sql", "vector", "market"],

        expected_sql=(
            "SELECT c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth "
            "FROM companies c "
            "JOIN financial_metrics fm ON fm.company_id = c.id "
            "WHERE c.ticker IN ('NVDA', 'AMD', 'CRM', 'ADBE') "
            "ORDER BY fm.revenue_growth DESC"
        ),

        # Read out of the database on 2026-08-21. A reseed moves all of
        # these — re-run the query rather than editing them by hand.
        expected_sql_result=[
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "pe_ratio": 33.20827, "eps": 6.53, "revenue_growth": 0.852},
            {"ticker": "AMD", "name": "Advanced Micro Devices, Inc.", "pe_ratio": 119.75893, "eps": 3.92, "revenue_growth": 0.501},
            {"ticker": "CRM", "name": "Salesforce, Inc.", "pe_ratio": 23.776619, "eps": 8.64, "revenue_growth": 0.133},
            {"ticker": "ADBE", "name": "Adobe Inc.", "pe_ratio": 15.564322, "eps": 17.49, "revenue_growth": 0.127},
        ],

        sql_order_requirement="none",

        # UNFINISHED — reference_answer, reference_contexts and
        # expected_ranking are Sathwika's, and are absent rather than
        # stubbed: an empty reference_contexts scores as a retrieval
        # failure and a placeholder answer as a real one.
        #
        #   uv run python -m backend.evaluation.datasets.read_corpus \
        #       NVDA AMD CRM ADBE --python

        reference_answer = (
    "NVIDIA Corporation (NVDA) ranks first overall in this comparison, "
    "followed by Advanced Micro Devices, Inc. (AMD), Salesforce, Inc. (CRM), and Adobe Inc. (ADBE).\n\n"
    "NVIDIA Corporation (NVDA) leads the group with unparalleled AI hardware demand and massive multi-year contract momentum. "
    "NVIDIA is backed by multibillion-dollar neocloud supply deals (including CoreWeave) and long-term lease commitments totaling up to $50B "
    "for Hut 8's Texas data centers to secure GPU infrastructure.\n\n"
    "Advanced Micro Devices, Inc. (AMD) ranks second, exhibiting strong Q2 operational performance, institutional position expansion "
    "(such as Wyoming's 87.9% stake increase), and analyst price targets reaching $546.87, though high valuation multiples and recent insider sales temper its top-tier placement.\n\n"
    "Salesforce, Inc. (CRM) ranks third, demonstrating accelerated enterprise software monetization and strong revenue execution. "
    "Salesforce benefits from Agentforce and Data Cloud ARR expansion, positive Q2 earnings expectations with Oppenheimer reiterating an Outperform rating ($250 price target), "
    "and new collaborative developer features like Slack Code.\n\n"
    "Adobe Inc. (ADBE) ranks fourth. While Adobe passes value screens with high margins and cash generation, persistent market concerns regarding AI disruption risk "
    "and flat ARR growth keep its broker ratings constrained."
),

reference_contexts = [
    # NVDA
    "CoreWeave Inc. has secured a multiyear, multibillion-dollar agreement with Hudson River Trading, granting Hudson River access to Nvidia's Vera Rubin and B200 AI systems. This deal highlights Wall Street's increasing demand for Nvidia's advanced AI chips for tasks like training trading models and analyzing data. CoreWeave has been raising prices for its AI cloud services, driven by this high demand and its early validation of Nvidia's new platforms.",
    "Hut 8 Corp. (HUT) stock is experiencing a significant surge due to massive long-term AI deals with Nvidia, repositioning the company from a crypto miner to a power-first AI infrastructure operator. These deals, reportedly totaling up to $50 billion over 30 years for its Texas data centers, have led to bullish upgrades and higher price targets from numerous Wall Street firms.",

    # AMD
    "The State of Wyoming significantly increased its holdings in Advanced Micro Devices (AMD) by 87.9% in Q2, purchasing an additional 2,540 shares to bring its total to 5,431 shares valued at $3.16 million. Institutional investors now own 71.34% of AMD, with many funds increasing their stakes. Despite strong Q2 results, a \"Moderate Buy\" consensus from analysts, and a target price of $546.87, the stock faces risks due to high valuation and recent insider sales.",

    # CRM
    "Salesforce announces Slack Code, a new feature designed to "
    "bring AI-powered coding agents and software development into "
    "a collaborative, multiplayer environment within Slack. This "
    "allows teams to work with agents like Claude Code, GitHub "
    "Copilot, and ChatGPT directly in dedicated \"code channels\" "
    "where they can write, review, and ship code together.",
    "Oppenheimer has reiterated an Outperform rating on Salesforce (NYSE:CRM) with a $250 price target, anticipating favorable second-quarter earnings. The firm believes Salesforce is currently undervalued and expects upside to consensus estimates, driven by strong new Agentforce and Data Cloud annual recurring revenue.",

    # ADBE
    "Adobe bottomed after AI-driven fears and is now trading at highly attractive valuations with strong growth prospects. Read why ADBE stock is a Strong Buy.",
    "Adobe downgraded to Strong Sell despite a 30% rebound: AI "
    "disruption risk persists, ARR growth is flat, and freemium "
    "isnât lifting revenue. Click for more on ADBE stock."
],

expected_ranking = ["NVDA", "AMD", "CRM", "ADBE"],
    ),

    # ------------------------------------------------------------------
]

QUESTIONS = ORIGINALS + AUTHORED
