"""
The sentiment set: 25 authored questions.

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

AUTHORED: list[EvalQuestion] = [
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
    # 23 more. Each candidate below is a whole question — the text is
    # written out ready to paste, with the cohort it is about and the
    # reason that cohort is worth asking about. The reference_answer,
    # reference_contexts and expected_ranking are yours; deciding them is
    # the work these questions exist to capture.
    #
    # The questions are deliberately neutral. The thing each one is
    # probing is described in the note underneath, never in the question
    # itself — a question that warns the pipeline about the trap does not
    # test whether it falls in.
    #
    # Read a cohort's evidence before writing it up:
    #
    #     uv run python -m backend.evaluation.datasets.read_corpus AXP MA PYPL
    #
    # Nothing here is binding. If a cohort reads thinner than the note
    # suggests, change the cohort and keep the shape — the shape is what
    # the set is short of, not the ticker list.
    #
    #
    # ---- coverage that is about someone other than the company --------
    #
    # sentiment_003   AXP MA PYPL
    #   "Rank American Express, Mastercard and PayPal by the sentiment of
    #    their recent coverage, and support the ranking with evidence from
    #    the retrieved documents."
    #
    #   The loudest coverage is not the most positive. Eight of Amex's ten
    #   documents are institutional-stake filings that read bullish by
    #   volume; the substantive two are an antitrust appeal it lost and a
    #   report that it is cutting customer credit limits.
    #
    EvalQuestion(
        question_id="sentiment_003",
        question=(
            "Rank American Express, Mastercard and PayPal by the sentiment of "
            "their recent coverage, and support the ranking with evidence from "
            "the retrieved documents."
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
            "Based on the provided documents, Mastercard (MA) exhibits the strongest positive sentiment, driven by new institutional positions from Pershing Square (Bill Ackman), strong growth fundamentals, a bullish technical setup, and key strategic partnerships (Fiserv, American Airlines, Borderless.xyz).\n\n"
            "American Express (AXP) holds a mixed but generally positive sentiment: while it reports strong Q2 earnings beating EPS estimates ($4.53), reaffirmed FY guidance, and significant institutional buying with a consensus 'Moderate Buy' rating, it faces notable headwinds from a lost antitrust appeal regarding merchant arbitration and defensive credit limit cuts/account cancellations.\n\n"
            "PayPal (PYPL) reflects a moderately positive sentiment driven by new tuition payment expansions for PayPal and Venmo across major education platforms and acquisition/turnaround interest from Stripe/Advent, though analyst sentiment remains conservative with a 'Hold' rating from Truist Securities."
        ),
    
        # VERBATIM from document_chunks. Printed by:
        #   read_corpus NVDA AMD INTC --python
        reference_contexts=[
            # Mastercard (MA)
            "Bill Ackman buys Netflix, Visa, Mastercard & S&P Global at compressed valuations.",
            "Mastercard: A Rare Growth Stock I'm Comfortable Buying At 28.5x Earnings",
            "In recent days, Mastercard’s Eastern Europe, Middle East and Africa unit named 20-year company veteran Yasemin Bedir as its next president effective September 1, 2026, while the company also expanded collaborations ranging from crypto-compliant cross-border stablecoin payments with Borderless.xyz to merchant cloud services with Fiserv and enhanced co-branded card benefits with American Airlines and Citi. At the same time, Bill Ackman’s Pershing Square has disclosed a new position in...",
            "Discover why Mastercard (NYSE:MA) passes a strong-growth screen with solid fundamentals and a bullish technical breakout setup for potential entry.",
            "Pershing Square initiated positions in Visa and Mastercard, citing their dominant network status. Read the full analysis for more details.",

            # American Express (AXP)
            "The U.S. Court of Appeals for the First Circuit has affirmed a lower court's decision, denying American Express's attempt to force antitrust claims from thousands of merchants into arbitration. The merchants allege that American Express's anti-steering and non-discrimination provisions violate federal antitrust law.",
            "Puzo Michael J has acquired a new stake of 19,362 shares in American Express Company (NYSE:AXP), valued at approximately $6.55 million, making it a 1.7% holding in their investment portfolio. This comes as American Express reported strong quarterly earnings, beating EPS estimates, and maintaining positive fiscal guidance. The company also continues to expand its premium partnerships and virtual-card services.",
            "American Express reported strong Q2 earnings, beating analyst estimates, and has an average \"Moderate Buy\" rating from analysts with an average price target of $373.32.",
            "American Express is reportedly implementing aggressive "
            "risk-management measures in the U.S., including cutting "
            "credit limits and canceling accounts for some customers. This "
            "action, previously seen during the 2008 financial crisis and "
            "the 2020 pandemic, suggests the company may be preparing for "
            "an economic downturn. The changes affect even charge cards "
            "like Platinum, with some cardholders seeing drastic "
            "reductions in their spending limits.",
            "Flossbach Von Storch SE has acquired a new stake of 91,144 shares in American Express Company (NYSE:AXP) during the second quarter, valued at approximately $30.83 million. Other institutional investors have also adjusted their positions in American Express, which recently reported strong quarterly earnings, exceeding analyst expectations with $4.53 EPS. The company also declared a quarterly dividend of $0.95 and maintains a \"Moderate Buy\" average rating from analysts.",
            "Asahi Life Asset Management CO. LTD. has acquired 7,546 shares of American Express Company (NYSE:AXP) valued at approximately $2.55 million, making it their 16th-largest portfolio holding. American Express reported strong Q2 earnings with EPS of $4.53 and revenue up 10% year-over-year, reaffirming its FY 2026 EPS guidance. Analyst sentiment remains largely positive, with a \"Moderate Buy\" consensus rating and an average price target of $373.32, despite a recent downgrade from one firm.",

            # PayPal (PYPL)
            "PayPal is reportedly back in takeover talks with Stripe and Advent, with expectations for an improved acquisition offer. Read why PYPL stock is a Strong Buy.",
            "PayPal (Nasdaq: PYPL) today announced new integrations with three of the nation's leading education payment platforms, Illumia, Nelnet Campus Commerce, and TouchNet, that give students and their families the option to pay tuition and fees directly with PayPal or Venmo. These integrations are live at schools across the nation, including Bellarmine University, Butler University, Kansas State University, Michigan State University, and Texas Tech University, with more institutions expected to join t",
            "Truist Securities  analyst Matthew Coad   maintains PayPal "
            "Holdings (NASDAQ:PYPL) with a Hold and raises the price "
            "target from $59 to $62."
        ],
    
        # The order the reference answer argues for.
        expected_ranking=["MA", "AXP", "PYPL"],
    ),
    # sentiment_004   MS JPM SCHW
    #   "Which of Morgan Stanley, JPMorgan and Charles Schwab has the most
    #    positive recent news coverage? Rank all three and cite the
    #    documents behind each placement."
    #
    #   Every Morgan Stanley document is Morgan Stanley research about
    #   somebody else — data-centre power, Merck, gold. An answer that
    #   reads those as sentiment on MS has confused the author with the
    #   subject.
    
    EvalQuestion(
            question_id="sentiment_004",
            question=(
                "Which of Morgan Stanley, JPMorgan and Charles Schwab has the most "
                "positive recent news coverage? Rank all three and cite the "
                "documents behind each placement."
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
                "The Charles Schwab Corporation (SCHW) has the most positive recent news coverage among the three firms. SCHW reported strong Q2 2026 earnings that exceeded analyst expectations ($1.62 EPS, $7.07 billion revenue), trades near its 12-month high with an elevated fair value estimate ($125.00), and attracted substantial institutional backing—including a $987.93 million new stake from Flossbach Von Storch SE.\n\n"
                "JPMorgan Chase & Co. (JPM) ranks second with strong positive coverage: Wells Fargo projected it could become the first $1 trillion market cap bank and potentially double again in 7-8 years, while General Atlantic selected JPM to lead a fresh IPO push and historical data highlighted its 5-year market outperformance (18.46% annualized return).\n\n"
                "Morgan Stanley (MS) ranks third with moderately positive coverage that primarily focuses on its analytical market research (predicting $5,000 gold by 2027 and identifying AI data center power shortages) and stock upgrades for third-party companies like Merck, rather than direct financial performance news about Morgan Stanley itself."
            ),

            # VERBATIM from document_chunks.
            reference_contexts=[
                # SCHW — The Charles Schwab Corporation
                "Charles Schwab stock is trading near its 12-month high, supported by strong second-quarter 2026 earnings and an updated fair value estimate of $125.00, which is above its current share price of $110.85. The company reported adjusted earnings of $1.62 per share and revenue of $7.07 billion, both exceeding analyst expectations, with robust net margins and return on equity. Institutional interest and a consistent dividend policy further bolster investor confidence in the stock's valuation.",
                "Great Lakes Advisors LLC recently purchased a new stake of $7.20 million in The Charles Schwab Corporation (NYSE:SCHW) during the second quarter. Other institutional investors like BlackRock and Danske Bank also increased their holdings, with institutional ownership now at 84.38%. Charles Schwab reported strong Q2 earnings, exceeding expectations with $1.62 EPS and $7.07 billion in revenue, and analysts maintain a \"Moderate Buy\" rating with an average price target of $121.17.",
                "Flossbach Von Storch SE has made a significant new investment in The Charles Schwab Corporation, purchasing over 10.7 million shares valued at approximately $987.93 million, making it their sixth-largest holding.",
                "Institutional investors collectively own 84.38% of Charles Schwab's stock, and analysts have set a consensus price target of $121.17, with most rating it a \"Buy\" or \"Strong Buy.\" The article also notes recent positive developments for Charles Schwab, such as increased client assets and strong earnings, alongside some insider selling and valuation concerns.",

                # JPM — JP Morgan Chase & Co.
                "JPMorgan Chase (NYSE:JPM) has outperformed the market over the past 5 years by 6.71% on an annualized basis producing an average annual return of 18.46%. Currently, JPMorgan Chase has a market capitalization of $959.71",
                "https://www.bloomberg.com/news/articles/2026-08-17/general-atlantic-is-said-to-tap-jpmorgan-to-lead-fresh-ipo-push",
                "Wells Fargo says JPMorgan could become the first $1 trillion bank, with potential to double its market cap within 7-8 years.",

                 # MS — Morgan Stanley
                "Lauren Hochfelder, head of global real assets at Morgan Stanley, suggests that industrial real estate offers an indirect avenue into the artificial intelligence sector. She discusses the current real estate market and how the expanding AI industry is increasingly influencing it. Her insights highlight the evolving relationship between technological advancements and property markets.",
                "Morgan Stanley projects a 38-gigawatt power deficit for U.S. AI data centers between 2026 and 2028, leading developers to seek faster power solutions. The article highlights three industrial stocks—GE Vernova, Eaton, and Vertiv—as key players to bridge this gap. These companies provide essential equipment for power generation, distribution, and cooling, making them critical beneficiaries of the AI infrastructure boom.",
                "Morgan Stanley has upgraded Merck's stock to overweight, raising its price target to $179, citing a strong cancer drug pipeline that is expected to drive growth even after its blockbuster drug Keytruda's patent expires in 2028. The firm believes new drugs and potential Keytruda co-formulations will mitigate the impact of the patent expiration and support future share growth.",
                "Morgan Stanley predicts gold prices could exceed $5,000 per ounce by 2027, despite an anticipated volatile path. The bank notes that gold reached its Q4 target earlier than expected, driven by increased ETF demand due to a lower implied probability of Federal Reserve rate hikes and central bank reserve building. Key risks include upcoming U.S. inflation data and low COMEX short positioning."
            ],

            # The order the reference answer argues for.
            expected_ranking=["SCHW", "JPM", "MS"],
            ),

    # sentiment_005   AMZN TSLA AAPL
    #   "Compare the tone of recent coverage for Amazon, Tesla and Apple.
    #    Rank them and say what each placement rests on."
    #
    #   The good news for one company sits inside a story about another:
    #   Delta chose Amazon over Starlink, and Musk responds. Positive for
    #   AMZN, filed as an AMZN document, and about a decision neither
    #   Amazon nor Tesla made.
    #

    EvalQuestion(
                question_id="sentiment_005",
                question=(
                    "Compare the tone of recent coverage for Amazon, Tesla and Apple. "
                    "Rank them and say what each placement rests on."
                ),
                expected_intent=IntentType.SENTIMENT,
                expected_tools=["planner", "vector"],
            
                reference_answer=(
        "Amazon.com, Inc. (AMZN) has the most positive coverage tone among the three companies. Its placement rests on strong long-term stock performance metrics (outperforming the market with a 24.36% average annual return over 15 years, turning $1,000 into over $27,000) and securing major enterprise contracts, such as Delta Air Lines selecting Amazon's satellite WiFi over Starlink for inflight connectivity.\n\n"
        "Apple Inc. (AAPL) ranks second with a mixed coverage tone. On the positive side, coverage highlights stock resilience following a 10% correction and analyst Gene Munster viewing Apple as an underappreciated AI winner with bullish technicals. However, this is tempered by noted margin pressures from rising memory costs and institutional selling, including Viking Global dumping its Apple shares.\n\n"
        "Tesla, Inc. (TSLA) exhibits the weakest coverage tone. Its placement rests on stock price decline (slipping 2%) due to heavy capital spending pressures on AI infrastructure, alongside significant institutional disinvestment, with Viking Global slashing its Tesla stake by 78% in Q2."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # AMZN — Amazon.com, Inc.
        "This article highlights the significant returns an investment in Amazon.com stock would have yielded over 15 years. An initial investment of $1,000 in AMZN 15 years ago would now be worth over $27,000, demonstrating the power of compounded returns. Amazon.com has outperformed the market with an average annual return of 24.36% over this period.",
        "Delta Air Lines chose Amazon's satellite WiFi over Starlink for its inflight connectivity, a decision Elon Musk claims will lead to passenger losses. Delta's CEO defends the choice, citing brand integration, while Musk points to passengers switching airlines. Other airlines, however, are adopting Starlink, raising concerns about Delta's competitive position if it doesn't offer comparable WiFi.",

        # AAPL — Apple Inc.
        "AAPL holds steady despite market dip. Gene Munster eyes Apple as an underappreciated AI winner as technicals stay bullish.",
        "Apple stock (AAPL) stays resilient after a 10% correction. AAPL faces margin pressure from a historic memory price upcycle. See more details here.",
        "Viking Global&#39;s Andreas Halvorsen shifts gears in Q2, "
        "making an $817M bet on Ferrari while slashing Tesla by 78% "
        "and dumping Apple.",

        # TSLA — Tesla, Inc.
        "Ford shares dropped 4% after a rally based on unconfirmed Bronco product reports faded, while General Motors gained 1%, indicating a company-specific reversal for Ford rather than a sector trend. Tesla also slipped 2% due to unrelated AI infrastructure capital-spending pressures. Investors are advised to exercise patience with Ford and monitor its upcoming Bronco recall notification on August 24.",
        
    ],

    # The order the reference answer argues for.
    expected_ranking=["AMZN", "AAPL", "TSLA"],
                
                ),




    #
    # ---- articles that disagree with each other -----------------------
    #
    # sentiment_006   MRK AMGN PFE
    #   "Rank Merck, Amgen and Pfizer by the sentiment of their recent
    #    coverage. Where the documents disagree about a company, say so
    #    and explain which way you read it."
    #
    #   Merck is upgraded to Overweight by Morgan Stanley and given a $170
    #   target, downgraded to Sector Perform by RBC, and lowered by
    #   Jefferies, all in the same window. Amgen has two clean target
    #   raises. Which way Merck ranks is the question.
    
    
      EvalQuestion(
                     question_id="sentiment_006",
                     question=(
                         "Rank Merck, Amgen and Pfizer by the sentiment of their recent "
                         "coverage. Where the documents disagree about a company, say so "
                         "and explain which way you read it."
                     ),
                     expected_intent=IntentType.SENTIMENT,
                     expected_tools=["planner", "vector"],
                 
                     reference_answer=(
        "Amgen Inc. (AMGN) has the most positive recent news coverage among the three companies. Analysts at Piper Sandler and Argus Research raised their price targets significantly to $457 and $460 respectively, maintaining Overweight/Buy ratings. Although Amgen issued a notice to terminate a research collaboration agreement with TScan Therapeutics, overall coverage remains strongly positive due to unanimous target price upgrades.\n\n"
        "Merck & Company, Inc. (MRK) ranks second with mixed coverage. Documents show a clear split among analysts: BMO Capital Markets (target raised to $170) and Morgan Stanley (upgraded to Overweight with a $179 target) cite strong Q2 earnings beats and promising late-stage Phase 3 melanoma vaccine results combined with Keytruda. Conversely, Royal Bank of Canada downgraded MRK to 'Sector Perform' ($150 target) and Jefferies downgraded it from 'Strong Buy' to 'Hold', pointing to patent expiration and regulatory risks alongside ~$30 million in recent insider stock sales. I read MRK as leaning moderately positive overall because the broad consensus remains a 'Moderate Buy' backed by strong pipeline progress.\n\n"
        "Pfizer, Inc. (PFE) exhibits the weakest coverage sentiment. While PFE reported strong Q2 earnings ($0.77 EPS, $15.03B revenue) and progress in its obesity pipeline, analyst consensus sits at a cautious 'Hold' due to a looming patent cliff. Furthermore, PFE faces legal and financial uncertainty after establishing a settlement program to resolve ~5,000 federal lawsuits regarding Depo-Provera intracranial meningioma claims."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # AMGN — Amgen Inc.
        "Piper Sandler  analyst David Amsellem   maintains Amgen "
        "(NASDAQ:AMGN) with a Overweight and raises the price target "
        "from $427 to $457.",
        "Argus Research  analyst Jasper Hellweg   maintains Amgen "
        "(NASDAQ:AMGN) with a Buy and raises the price target from "
        "$375 to $460.",
        "On August 12, 2026, TScan Therapeutics, Inc. (the "
        "&#34;Company&#34;) received notice from Amgen Inc. "
        "(&#34;Amgen&#34;) of its election to terminate, in its "
        "entirety, the Research Collaboration and License Agreement,",

        # MRK — Merck & Company, Inc.
        "BMO Capital Markets raised Merck & Co., Inc.'s (NYSE:MRK) price target to $170.00 from $142.00, maintaining an \"outperform\" rating with a potential upside of 12.49%. This comes amidst mixed analyst sentiment, although the consensus rating remains \"Moderate Buy\" with an average target of $142.10. The company's recent quarterly results surpassed expectations, and its Keytruda-personalized cancer vaccine program shows promise, despite significant insider stock sales.",
        "Royal Bank of Canada downgraded Merck & Co., Inc. (NYSE:MRK) from an \"outperform\" to a \"sector perform\" rating, setting a $150 price target, which implies a slight downside from its current price. Despite this downgrade, the overall analyst sentiment remains positive, with a \"Moderate Buy\" consensus and an average price target of $139.20.",
        "The company recently exceeded earnings and revenue expectations, and its shares are trading near their 52-week high, although insiders have sold almost $30 million in stock over the past 90 days.",
        "Morgan Stanley upgraded Merck & Co., Inc. (NYSE:MRK) from \"equal weight\" to \"overweight\" and increased its price target from $116 to $179, suggesting a 17.6% upside. This upgrade follows positive late-stage results for Merck's personalized melanoma vaccine combined with Keytruda, which strengthens its oncology pipeline.",
        "Jefferies Financial Group has downgraded Merck & Co., Inc. (NYSE:MRK) from a \"strong-buy\" to a \"hold\" rating, despite a broader analyst consensus of \"moderate buy.\" The downgrade follows Merck's recent positive Phase 3 results for a personalized melanoma vaccine combined with Keytruda, which presents a significant growth opportunity, but also comes with regulatory and patent expiry risks.",

        # PFE — Pfizer, Inc.
        "This article examines the potential for Pfizer, Chevron, and AbbVie to reach ambitious price targets by 2027, driven by strong quarterly results and strategic initiatives. Pfizer aims for $35 due to its obesity drug pipeline and cost savings, while Chevron targets $250 supported by its Guyana assets, Hess synergies, and a power deal with Microsoft. AbbVie eyes $325, propelled by the growth of Skyrizi and Rinvoq, along with an acquisition.",
        "Janney Montgomery Scott LLC has increased its stake in Pfizer Inc. by 3.4% during the second quarter, bringing its total holdings to 2.41 million shares valued at approximately $58.14 million. Pfizer recently reported strong quarterly earnings of $0.77 per share and revenue of $15.03 billion, surpassing analyst expectations, and declared a quarterly dividend of $0.43 per share.",
        "Despite an average \"Hold\" rating from analysts and concerns about a looming patent cliff, the stock is showing positive sentiment due to pipeline developments and unusual call-option activity.",
        "Pfizer (NYSE:PFE) has established a settlement program aimed at resolving a significant portion of federal lawsuits concerning Depo-Provera intracranial meningioma, potentially covering around 5,000 of over 6,200 pending claims. This confidential agreement is a crucial legal development that could impact Pfizer's litigation reserves, risk profile, and public perception."
    ],

    # The order the reference answer argues for.
    expected_ranking=["AMGN", "MRK", "PFE"],
                     
                     ),



    # sentiment_007   ABT TMO DHR
    #   "Which of Abbott, Thermo Fisher and Danaher has the most positive"
    #    "recent coverage? Rank them and support each placement with the"
    #    "retrieved documents."
    #
    #   One company carrying an upgrade and a downgrade at once: Abbott is
    #   upgraded to Outperform by Wolfe with a $130 target, and downgraded
    #   in another note whose headline is otherwise positive about
    #   diagnostics and devices.
    
     EvalQuestion(
                         question_id="sentiment_007",
                         question=(
                                "Which of Abbott, Thermo Fisher and Danaher has the most positive "
                                "recent coverage? Rank them and support each placement with the "
                                "retrieved documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                         reference_answer=(
        "Abbott Laboratories (ABT) has the most positive recent coverage among the three companies. ABT's coverage is driven by a strong Q2 earnings beat and raise, an analyst upgrade from Wolfe Research (Mike Polark) from Peer Perform to Outperform with a $130 price target, and solid fundamentals in diagnostics and medical devices, despite minor insider sales reported by politicians.\n\n"
        "Thermo Fisher Scientific Inc (TMO) ranks second with moderately positive coverage: reports cite biopharma recovery and market share gains supporting stock upside, alongside news of TMO successfully closing the $1.1 billion sale of its microbiology unit to private equity firm Astorg.\n\n"
        "Danaher Corporation (DHR) exhibits the weakest sentiment. Although one report notes potential 2027 growth reacceleration, its recent Q2 2026 earnings results revealed that its bioprocessing unit missed expectations due to persistent softness in biopharma demand, and the stock was listed among large-caps viewed as risky."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # ABT — Abbott Laboratories
        "Abbott Laboratories is a Buy due to higher valuation, but "
        "expect low-teens annual total returns supported by strong "
        "fundamentals. Read more on ABT stock here.",
        "Abbott stays a buy after Q2 beat/raise; Exact Sciences boosts "
        "growth. Click for more on ABT stock.",
        "Wolfe Research  analyst Mike Polark   upgrades Abbott "
        "Laboratories (NYSE:ABT) from Peer Perform to Outperform and "
        "announces $130 price target.",

        # TMO — Thermo Fisher Scientific Inc
        "Thermo Fisher Scientific: Biopharma Recovery And Share Gains Support The Upside",
        "European private equity firm Astorg will run the business as an independent diagnostics company, led by former PerkinElmer CEO Dirk Bontridder.",

        # DHR — Danaher Corporation
        "When biopharmaceutical suppliers report earnings, ripples "
        "move fast across the sector. On July 21, Danaher Corporation "
        "(NYSE:DHR) reported its Q2 2026 results. While the life "
        "sciences giant continues to lead in financial scale, its "
        "bioprocessing unit missed expectations, signaling continued "
        "softness in broader biopharma demand. The news hit European "
        "supplier Sartorius AG, which traded lower […]",
        "Danaher: 2027 Growth Reacceleration Should Drive Upside"
    ],

    # The order the reference answer argues for.
    expected_ranking=["ABT", "TMO", "DHR"],
                         
                         ),
    # sentiment_008   HD MCD SBUX
    #    "Rank Home Depot, McDonald's and Starbucks by the sentiment of"
    #    "their recent news coverage, and explain the evidence behind the"
    #    "order."
    #
    #   Home Depot's Q2 is read both ways in the same week — Mizuho raises
    #   its target, UBS lowers its, one note calls it green shoots and
    #   another mundane with lingering risks. Two of the nine documents
    #   are about Lowe's, not Home Depot.
    #
    

     EvalQuestion(
                         question_id="sentiment_008",
                         question=(
                             "Rank Home Depot, McDonald's and Starbucks by the sentiment of "
                             "their recent news coverage, and explain the evidence behind the "
                             "order."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                         reference_answer=(
        "Home Depot, Inc. (HD) has the most positive recent coverage among the three companies. Its placement rests on strong Q2 2026 earnings that beat analyst estimates, revenue growth of 5.7%, solid digital sales momentum, and sustained institutional support with analyst price target upgrades (such as Mizuho raising its target to $390 and UBS maintaining a Buy rating), despite some noted caution around DIY consumer demand and potential tariff/cost pressures.\n\n"
        "McDonald's Corporation (MCD) ranks second with moderately positive to neutral coverage. Its sentiment is supported by menu innovation and growth strategy execution, specifically highlighting the official addition of energy drinks to its menu through the debut of the Red Bull Dragonberry Energizer.\n\n"
        "Starbucks Corporation (SBUX) exhibits the weakest coverage sentiment by a wide margin. Its placement is driven by significant operational and legal headwinds, including shedding over 100 jobs to wrap up corporate restructuring and Starbucks Korea recording its first quarterly operating loss in 27 years following a PR debacle, consumer boycott, public criticism from President Lee Jae Myung, and a police raid of its corporate offices."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # HD — Home Depot, Inc. (The)
        "Mizuho  analyst David Bellinger   maintains Home Depot "
        "(NYSE:HD) with a Outperform and raises the price target from "
        "$385 to $390.",
        "HD shares rallied after upbeat Q2 results. Analysts have mixed ratings and price targets, with some noting potential cost pressures.",
        "The Home Depot's Q2 earnings beat slightly, but shares stayed flat. Click for this updated look at HD stock and see why I remain bearish.",
        "Home Depot delivered a strong Q2 2026 with 5.7% revenue growth and solid digital sales momentum but remains rangebound. Click here for this HD stock update.",
        "UBS  analyst Michael Lasser   maintains Home Depot (NYSE:HD) "
        "with a Buy and lowers the price target from $430 to $420.",
        "Home Depot (HD) reports better-than-expected Q2 earnings with sales above estimates. Analysts maintain Buy rating and raise price targets.",

        # MCD — McDonald's Corporation
        "McDonald's (MCD) officially added energy drinks to its menu for the first time today with the debut of its new Red Bull Dragonberry Energizer.",
        "Part of the company's growth strategy is to add interesting menu items while simplifying operations.",

        # SBUX — Starbucks Corporation
        "https://www.bloomberg.com/news/articles/2026-08-20/starbucks-sheds-more-than-100-jobs-as-it-wraps-up-restructuring",
        "Starbucks Korea posted its first quarterly loss since it started operations 27 years ago after a marketing debacle triggered a boycott, criticism from President Lee Jae Myung, and a police raid of its corporate offices."
    ],

    # The order the reference answer argues for.
    expected_ranking=["HD", "MCD", "SBUX"],
                         
                         ),
    # ---- the obvious answer is wrong ----------------------------------
    #
    # sentiment_009   NKE SBUX AMZN
    #    "Based on recent coverage, which of Nike, Starbucks and Amazon is"
    #    "viewed most favourably? Rank them and cite the documents."
    #
    #   Two of the three have a "$1,000 invested N years ago" piece that
    #   reads positive and says nothing about now. Starbucks' current news
    #   is a restructuring that shed 100+ jobs and Starbucks Korea's first
    #   loss in 27 years; Nike is the mirror image, an 80% drawdown and a
    #   "stage 4 breakdown" warning alongside a fund manager buying it
    #   after a six-year hiatus.
    

     EvalQuestion(
                         question_id="sentiment_009",
                         question=(
                             "Based on recent coverage, which of Nike, Starbucks and Amazon is "
                             "viewed most favourably? Rank them and cite the documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                         reference_answer=(
        "Amazon.com, Inc. (AMZN) is viewed most favourably among the three companies based on the provided coverage. Its top placement rests on strong long-term stock performance metrics (outperforming the market over 15 years with an average annual return of 24.36%, turning $1,000 into over $27,000) and securing major commercial contracts, such as Delta Air Lines choosing Amazon's satellite WiFi over Starlink for inflight connectivity.\n\n"
        "Starbucks Corporation (SBUX) ranks second with mixed-to-negative coverage. On the positive side, historical data notes that Starbucks has outperformed the market over the past 20 years with an average annual return of 10.45%. However, recent coverage highlights significant headwinds, including shedding over 100 jobs to wrap up restructuring and Starbucks Korea recording its first quarterly loss in 27 years due to a marketing debacle, consumer boycott, public criticism from President Lee Jae Myung, and a police raid.\n\n"
        "NIKE, Inc. (NKE) exhibits the weakest coverage sentiment. While one investor noted buying shares after a six-year hiatus, major coverage emphasizes severe technical and financial distress, reporting that NKE stock has erased $200 billion in market cap, crashed nearly 80% from its 2021 peak, and faced Wall Street warnings of a 'Stage 4' technical breakdown."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # AMZN — Amazon.com, Inc.
        "This article highlights the significant returns an investment in Amazon.com stock would have yielded over 15 years. An initial investment of $1,000 in AMZN 15 years ago would now be worth over $27,000, demonstrating the power of compounded returns. Amazon.com has outperformed the market with an average annual return of 24.36% over this period.",
        "Delta Air Lines chose Amazon's satellite WiFi over Starlink for its inflight connectivity, a decision Elon Musk claims will lead to passenger losses. Delta's CEO defends the choice, citing brand integration, while Musk points to passengers switching airlines. Other airlines, however, are adopting Starlink, raising concerns about Delta's competitive position if it doesn't offer comparable WiFi.",

        # SBUX — Starbucks Corporation
        "Starbucks (NASDAQ:SBUX) has outperformed the market over the past 20 years by 1.11% on an annualized basis producing an average annual return of 10.45%. Currently, Starbucks has a market capitalization of $125.56",
        "https://www.bloomberg.com/news/articles/2026-08-20/starbucks-sheds-more-than-100-jobs-as-it-wraps-up-restructuring",
        "Starbucks Korea posted its first quarterly loss since it started operations 27 years ago after a marketing debacle triggered a boycott, criticism from President Lee Jae Myung, and a police raid of its corporate offices.",

        # NKE — NIKE, Inc.
        "Nike stock has erased $200B in market cap since 2021. Read "
        "why Arvy&#39;s CIO warns NKE faces a severe &#39;Stage 4&#39; "
        "technical decline.",
        "Why I Bought Nike After A 6-Year Hiatus"
    ],

    # The order the reference answer argues for.
    expected_ranking=["AMZN", "SBUX", "NKE"],
                         
                         ),
    # sentiment_010   WMT HD NKE
    #   "Which of Walmart, Home Depot and Nike has the most positive
    #    recent news coverage? Rank them and support the ranking with
    #    evidence from the retrieved documents."
    #
    #   Seven of Walmart's nine documents are most-active-stock screeners
    #   with no sentiment in them; the one that matters says Walmart
    #   tumbled on weak U.S. sales. Tests whether volume of coverage is
    #   being mistaken for tone.
    
     EvalQuestion(
                         question_id="sentiment_010",
                         question=(
                              "Which of Walmart, Home Depot and Nike has the most positive "
        "recent news coverage? Rank them and support the ranking with "
       "evidence from the retrieved documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                        
                        reference_answer=(
        "Home Depot, Inc. (HD) has the most positive recent coverage among the three companies. Its placement rests on better-than-expected Q2 2026 earnings with sales beating estimates, 5.7% revenue growth, digital sales momentum, and analyst price target upgrades (such as Mizuho raising its target to $390 and UBS maintaining a Buy rating), despite some noted caution around DIY demand and cost pressures.\n\n"
        "Walmart Inc. (WMT) ranks second with negative sentiment. While it featured prominently among active S&P 500 movers following its Q2 earnings call, its coverage highlighted that the stock tumbled after issuing cautious guidance and flashing warnings about weak U.S. consumer spending.\n\n"
        "NIKE, Inc. (NKE) ranks third with the most severe negative coverage. Although one investor noted buying shares after a six-year hiatus, major coverage emphasizes severe technical and financial decline, noting that NKE stock has erased $200 billion in market cap, crashed nearly 80% from its 2021 peak, and faced Wall Street warnings of a 'Stage 4' technical breakdown."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # HD — Home Depot, Inc. (The)
        "Mizuho  analyst David Bellinger   maintains Home Depot "
        "(NYSE:HD) with a Outperform and raises the price target from "
        "$385 to $390.",
        "HD shares rallied after upbeat Q2 results. Analysts have mixed ratings and price targets, with some noting potential cost pressures.",
        "The Home Depot's Q2 earnings beat slightly, but shares stayed flat. Click for this updated look at HD stock and see why I remain bearish.",
        "Home Depot delivered a strong Q2 2026 with 5.7% revenue growth and solid digital sales momentum but remains rangebound. Click here for this HD stock update.",
        "UBS  analyst Michael Lasser   maintains Home Depot (NYSE:HD) "
        "with a Buy and lowers the price target from $430 to $420.",
        "Home Depot (HD) reports better-than-expected Q2 earnings with sales above estimates. Analysts maintain Buy rating and raise price targets.",

        # WMT — Walmart Inc.
        "Walmart (WMT) flashed a warning about consumer spending with cautious guidance in its latest earnings report.",
        "Walmart Inc. (WMT) Q2 2027 Earnings Call August 20, 2026 8:00 AM EDTCompany ParticipantsStephanie Wissink - Senior Vice President of Investor RelationsJohn...",

        # NKE — NIKE, Inc.
        "Nike stock has erased $200B in market cap since 2021. Read "
        "why Arvy&#39;s CIO warns NKE faces a severe &#39;Stage 4&#39; "
        "technical decline.",
        "Why I Bought Nike After A 6-Year Hiatus"
    ],

    # The order the reference answer argues for.
    expected_ranking=["HD", "WMT", "NKE"],
                         
                         
                         ),
    # sentiment_011   AAPL ADBE CRM
    #   "Rank Apple, Adobe and Salesforce by the sentiment of their recent
    #    coverage and explain the evidence behind each placement."
    #
    #   The same trap in tech: much of Apple's file is "which Dow stocks
    #   are moving", while Adobe has a real bull-and-bear pair and
    #   Salesforce has product launches and a discrimination ruling.
    #
    #
    # ---- a cohort that cannot reach its own evidence -------------------
    

     EvalQuestion(
                         question_id="sentiment_011",
                         question=(
                            "Rank Apple, Adobe and Salesforce by the sentiment of their recent "
        "coverage and explain the evidence behind each placement."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                        reference_answer=(
        "Salesforce, Inc. (CRM) exhibits the most positive coverage sentiment among the three companies. Its top placement rests on major product innovations—including the launch of 'Slack Code' for agentic multiplayer coding and Tableau AI agents in South Korea—along with strong financial backing, including an Oppenheimer 'Outperform' reiteration ($250 price target) anticipating revenue reacceleration from Agentforce and Data Cloud ARR, institutional share purchases by Asahi Life Asset Management, and a successful $250M funding participation in Muon Space.\n\n"
        "Apple Inc. (AAPL) ranks second with a mixed coverage tone. On the positive side, coverage highlights stock price stability following a 10% correction, bullish technicals, and analyst Gene Munster viewing Apple as an underappreciated AI winner. However, this is offset by margin pressure from rising memory costs and institutional selling, including Viking Global dumping its position.\n\n"
        "Adobe Inc. (ADBE) ranks third with the weakest overall coverage sentiment. Although some coverage highlights strong margins, free cash flow yield, and value pick potential, it faces significant disagreement and heavy negative analyst sentiment, including a 'Strong Sell' downgrade citing persistent AI disruption risks and flat ARR growth, as well as a B of A Securities 'Underperform' rating with a $220 target."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # CRM — Salesforce, Inc.
        "Salesforce announces Slack Code, a new feature designed to bring AI-powered coding agents and software development into a collaborative, multiplayer environment within Slack. This allows teams to work with agents like Claude Code, GitHub Copilot, and ChatGPT directly in dedicated \"code channels\" where they can write, review, and ship code together.",
        "Oppenheimer has reiterated an Outperform rating on Salesforce (NYSE:CRM) with a $250 price target, anticipating favorable second-quarter earnings. The firm believes Salesforce is currently undervalued and expects upside to consensus estimates, driven by strong new Agentforce and Data Cloud annual recurring revenue.",
        "Muon Space has successfully raised $250 million from investors including Google and Salesforce, with the funding aimed at expanding its FireSat wildfire detection constellation and increasing its satellite manufacturing capabilities to 500 spacecraft annually.",
        "Salesforce has launched Tableau AI agents in South Korea, aiming to transform analytics into actionable insights. This initiative will enable businesses in the region to leverage AI for data-driven decision-making and improved operational efficiency.",
        "Asahi Life Asset Management CO. LTD. has acquired 7,546 shares of Salesforce Inc. (NYSE:CRM) valued at approximately $1.18 million, contributing to institutional investors owning 80.43% of the company's stock. Salesforce maintains a \"Moderate Buy\" consensus rating with an average target price of $249.49, following strong quarterly earnings and revenue performance.",

        # AAPL — Apple Inc.
        "AAPL holds steady despite market dip. Gene Munster eyes Apple as an underappreciated AI winner as technicals stay bullish.",
        "Apple stock (AAPL) stays resilient after a 10% correction. AAPL faces margin pressure from a historic memory price upcycle. See more details here.",
        "Viking Global&#39;s Andreas Halvorsen shifts gears in Q2, "
        "making an $817M bet on Ferrari while slashing Tesla by 78% "
        "and dumping Apple.",

        # ADBE — Adobe Inc.
        "Adobe bottomed after AI-driven fears and is now trading at highly attractive valuations with strong growth prospects. Read why ADBE stock is a Strong Buy.",
        "B of A Securities  analyst Tal Liani   maintains Adobe "
        "(NASDAQ:ADBE) with a Underperform and raises the price target "
        "from $190 to $220.",
        "Adobe downgraded to Strong Sell despite a 30% rebound: AI "
        "disruption risk persists, ARR growth is flat, and freemium "
        "isnât lifting revenue. Click for more on ADBE stock."   ],

    # The order the reference answer argues for.
    expected_ranking=["CRM", "AAPL", "ADBE"],
                         
                         ),
    # sentiment_012   INTC NVDA AMD
    #   "Which of Intel, NVIDIA and AMD has the most positive recent news
    #    coverage? Rank them, and say where the retrieved documents do not
    #    support a confident placement."
    #
    #   AMD has one chunk — a state pension buying 2,540 shares. The
    #   article that would actually inform an AMD view, on its CPU-market
    #   AI opportunity, is filed under BAC and is unreachable from this
    #   cohort. Say the evidence is thin rather than inventing tone for
    #   it, and do not cite the BAC document: vector search is restricted
    #   to the cohort, so it can never be retrieved and would score 0.0.
    

     EvalQuestion(
                         question_id="sentiment_012",
                         question=(
                             "Which of Intel, NVIDIA and AMD has the most positive recent news "
        "coverage? Rank them, and say where the retrieved documents do not "
        "support a confident placement."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                         reference_answer=(
        "Intel Corporation (INTC) has the most positive recent coverage among the three companies. Its top ranking rests on massive market appreciation—where its stock nearly tripled in a single quarter to become 67% of SoftBank Group's U.S. stock portfolio ($12.1 billion value)—signaling a major vote of confidence in its AI and foundry roadmap, alongside strategic research initiatives on robotics readiness.\n\n"
        "NVIDIA Corporation (NVDA) ranks second with strong positive coverage: reports highlight intense Wall Street demand for its Vera Rubin and B200 AI systems via CoreWeave's multibillion-dollar deal with Hudson River Trading, as well as massive 30-year $50 billion AI infrastructure deals with Hut 8. However, the documents do not support a confident placement separating Intel and NVIDIA: both feature extraordinary positive sentiment driven by AI infrastructure demand, but Intel's coverage explicitly highlights direct stock price tripling while NVIDIA is primarily featured through its ecosystem partners (CoreWeave and Hut 8).\n\n"
        "Advanced Micro Devices, Inc. (AMD) ranks third with the weakest sentiment among the group. Although AMD reported strong Q2 results, institutional buying (such as the State of Wyoming expanding its stake by 87.9%), and a 'Moderate Buy' consensus with a $546.87 price target, its coverage explicitly highlights risks from high valuation and recent insider sales."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # INTC — Intel Corporation
        "SoftBank Group has made Intel (NasdaqGS: INTC) the largest component of its U.S. equity portfolio, with the stock representing nearly 67% of its disclosed holdings. This significant concentration signals a strong vote of confidence from SoftBank in Intel's AI and foundry roadmap, aligning with Intel's recent strategic shifts and capital raises.",
        "New Intel-commissioned research reveals that while six in 10 senior leaders anticipate operating robot fleets within five years, only four in 10 have a formal strategy for managing a mixed human-robot workforce. This \"Robotics Readiness Gap\" highlights a disconnect between ambition and operational readiness in the accelerating adoption of robotics.",
        "SoftBank Group's latest 13F filing reveals that Intel (INTC) now constitutes 67% of its U.S. stock portfolio, valued at $12.1 billion as of June 30. However, this high concentration is due to Intel's stock nearly tripling in the last quarter, not new purchases by Masayoshi Son, as SoftBank held the exact same number of shares.",
        "The article notes that while Intel's business performance is improving, the stock's valuation still appears expensive, especially given its recent price drop and the dilution from Intel's own share offering.",

        # NVDA — NVIDIA Corporation
        "Hut 8 Corp. (HUT) stock is experiencing a significant surge due to massive long-term AI deals with Nvidia, repositioning the company from a crypto miner to a power-first AI infrastructure operator. These deals, reportedly totaling up to $50 billion over 30 years for its Texas data centers, have led to bullish upgrades and higher price targets from numerous Wall Street firms.",
        "CoreWeave Inc. has secured a multiyear, multibillion-dollar agreement with Hudson River Trading, granting Hudson River access to Nvidia's Vera Rubin and B200 AI systems. This deal highlights Wall Street's increasing demand for Nvidia's advanced AI chips for tasks like training trading models and analyzing data. CoreWeave has been raising prices for its AI cloud services, driven by this high demand and its early validation of Nvidia's new platforms.",

        # AMD — Advanced Micro Devices, Inc.
        "The State of Wyoming significantly increased its holdings in Advanced Micro Devices (AMD) by 87.9% in Q2, purchasing an additional 2,540 shares to bring its total to 5,431 shares valued at $3.16 million. Institutional investors now own 71.34% of AMD, with many funds increasing their stakes. Despite strong Q2 results, a \"Moderate Buy\" consensus from analysts, and a target price of $546.87, the stock faces risks due to high valuation and recent insider sales."
    ],

    # The order the reference answer argues for.
    expected_ranking=["INTC", "NVDA", "AMD"],
                         
                         ),


    # sentiment_013   MSFT META GOOGL
    #   "Rank Microsoft, Meta and Alphabet by the sentiment of their
    #    recent coverage, and support the ranking with the retrieved
    #    documents."
    #
    #   Microsoft's single document is about Meta falling behind Amazon,
    #   Alphabet and Microsoft in AI — favourable to MSFT and GOOGL,
    #   damaging to META, and the only coverage two of the three have.
    #
     EvalQuestion(
                         question_id="sentiment_013",
                         question=(
                             "Rank Microsoft, Meta and Alphabet by the sentiment of their "
        "recent coverage, and support the ranking with the retrieved "
       "documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
              reference_answer=(
        "Microsoft Corporation (MSFT) has the most positive coverage sentiment among the three companies. Coverage highlights high investor confidence in MSFT's position in the AI race, where its market capitalization of $3.60 trillion significantly outpaces peers like Meta, reflecting strong market validation of its growth and AI strategy.\n\n"
        "Alphabet Inc. (GOOGL) ranks second with mixed coverage. On the positive side, coverage notes its market-leading AI standing and massive $4.19 trillion market capitalization alongside aggressive competitive strategies for YouTube (offering millions to creators for exclusive content to fend off Netflix). However, this is offset by short-term market pressure, as Alphabet shares fell sharply in a broader Big Tech ETF slump.\n\n"
        "Meta Platforms, Inc. (META) exhibits the weakest coverage sentiment by a wide margin. Documents highlight that Meta falls far behind Microsoft and Alphabet in the AI race, with investors questioning whether Mark Zuckerberg's 'AI manifesto' is merely a PR move, while private AI rivals like Anthropic near or surpass its valuation as confidence in its legacy social media business diminishes."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # MSFT — Microsoft Corporation
        "Meta's market capitalization of $1.39 trillion significantly lags behind Amazon ($2.87 trillion), Microsoft ($3.60 trillion), and Alphabet ($4.19 trillion) in the AI race, despite CEO Mark Zuckerberg's 14-page AI manifesto. Even private AI rival Anthropic is nearing or surpassing Meta's valuation, highlighting investors' diminished view of Meta's social media business and AI strategy compared to its tech giant peers.",
        "The article emphasizes market cap as a crucial indicator of investor confidence in the AI supremacy battle, noting that legacy businesses are becoming less relevant as AI's importance grows.",

        # GOOGL — Alphabet Inc.
        "An exchange-traded fund comprising seven major U.S. tech stocks, the Roundhill Magnificent Seven ETF, experienced a sharp decline on Thursday. Shares of Tesla, Amazon, and Alphabet were notably down, with Tesla suffering the largest loss of over 2%. The ETF's overall slump was recorded at 1.1% according to FactSet data.",
        "YouTube is offering millions to popular creators for exclusive video uploads, aiming to prevent them from simultaneously working with Netflix. This strategy includes direct financing of programs and sharing portions of major brand deals. Netflix has been paying YouTubers to cross-post content, seeking to attract younger audiences and expand its subscriber base, which YouTube views as a threat to its viewership and advertising revenue.",
        
        # META — Meta Platforms, Inc.
        "Mark Zuckerberg's \"AI manifesto,\" \"The Future is for Everyone,\" outlines a vision of democratized AI and personal superintelligence agents. However, the article questions whether Meta's past actions and current capabilities align with this ambitious vision, particularly concerning its commitment to open-source principles and its standing in the competitive AI landscape. It suggests that Meta's public stance might be more of a PR move to position itself amidst stronger AI contenders.",
        
    ],

    # The order the reference answer argues for.
    expected_ranking=["MSFT", "GOOGL", "META"],           
                         
                         ),


    # ---- sector cohorts rather than themes -----------------------------
    #
    # sentiment_014   XOM CVX COP
    #    "Rank Exxon Mobil, Chevron and ConocoPhillips by the sentiment of"
    #    "their recent news coverage. Where a company's coverage points"
    #    "both ways, say so."
    #
    #   Exxon's own file is split: a warning that Kazakhstan's top field
    #   peaks within years, against $1.1B of Rovuma LNG contracts and a
    #   20-year Targa agreement.
    

     EvalQuestion(
        question_id="sentiment_014",
        question=(
            "Rank Exxon Mobil, Chevron and ConocoPhillips by the sentiment of "
            "their recent news coverage. Where a company's coverage points "
            "both ways, say so."
        ),
        expected_intent=IntentType.SENTIMENT,
        expected_tools=["planner", "vector"],
        reference_answer=(
            "Chevron Corporation (CVX) has the most positive recent coverage among the three companies. CVX coverage highlights an analyst price target increase from Morgan Stanley, long-term market outperformance, and an international asset sale deal with Equinor for a stake in a Namibian offshore exploration license.\n\n"
            "ConocoPhillips (COP) ranks second with strong positive coverage that points slightly both ways: Morgan Stanley and Argus Research maintain bullish outlooks with price target increases, though Barclays slightly lowered its price target (while maintaining an Overweight rating). COP also appointed Chord Energy executive Shannon Kinney as General Counsel.\n\n"
            "ExxonMobil Holdings Corporation (XOM) ranks third with coverage pointing strongly both ways. On the positive side, XOM stock gained as crude oil topped $85, Morgan Stanley raised its price target (Overweight), Targa Resources executed a 20-year Permian Basin midstream deal with XOM, and XOM awarded over $1 billion in contracts for Rovuma LNG Phase 1. Conversely, negative coverage notes that XOM warned Kazakhstan's top oil field will peak within years, its best project's success is paradoxically lowering its share of oil, and investors are questioning whether the stock's powerful run has paused."
        ),
        reference_contexts=[
            # CVX — Chevron Corporation
            "Chevron (NYSE:CVX) has outperformed the market over the past 5 years by 5.03% on an annualized basis producing an average annual return of 16.35%. Currently, Chevron has a market capitalization of $411.82 billion.",
            "Morgan Stanley  analyst Devin McDermott   maintains Chevron (NYSE:CVX) with a Overweight and raises the price target from $210 to $218.",
            "https://www.equinor.com/news/20260818-equinor-chevron-namibia-exploration-licence",

            # COP — ConocoPhillips
            "Morgan Stanley  analyst Devin McDermott   maintains ConocoPhillips (NYSE:COP) with a Overweight and raises the price target from $147 to $151.",
            "Argus Research  analyst Bill Selesky   maintains ConocoPhillips (NYSE:COP) with a Buy and raises the price target from $136 to $153.",
            "Barclays  analyst Betty Jiang   maintains ConocoPhillips (NYSE:COP) with a Overweight and lowers the price target from $155 to $150.",
            "In early August 2026, Chord Energy reported past second-quarter results showing higher total production volumes year-on-year, sharply higher revenue of US$2.17 billion, a swing to net income of US$525.19 million, and confirmed new production guidance, a US$1.30 per-share base dividend, and completion of a US$265.92 million buyback tranche. The company also announced that long-serving executive Shannon Kinney will depart to become General Counsel at ConocoPhillips, while CEO Danny Brown...",

            # XOM — ExxonMobil Holdings Corporation
            "Targa Resources inks a 20-year ExxonMobil midstream deal, funding new plants and pipelines for long-term growth. Click for more on TRGP stock.",
            "https://www.bloomberg.com/news/articles/2026-08-20/exxon-warns-kazakhstan-s-top-oil-field-to-peak-within-years",
            "Morgan Stanley  analyst Devin McDermott   maintains ExxonMobil Holdings (NYSE:XOM) with a Overweight and raises the price target from $168 to $177.",
            "ExxonMobil shares rise as oil tops $85 amid Strait of Hormuz disruptions, while the energy sector gains about 40% year to date.",
            "Targa Resources Corp. (NYSE: TRGP) (&#34;Targa&#34; or the &#34;Company&#34;) today announced the execution of new long-term, integrated midstream agreements with subsidiaries of ExxonMobil, further strengthening the",
            "https://corporate.exxonmobil.com/locations/mozambique/mozambique-newsroom/exxonmobil-mozambique-and-area-4-coventurers-award-over-1-b-usd-in-contracts-for-rovuma-lng",
            "ExxonMobil's latest earnings call forced management to explain a strange problem: why its best project is so successful that the company's share of the oil is now falling.",
            "A powerful run has paused, forcing investors to decide if this energy giant's operational engine has more fuel or if the market has already paid for the whole trip."
        ],
        expected_ranking=["CVX", "COP", "XOM"],
    ),
    # sentiment_015   SLB EOG COP
    #   "Which of SLB, EOG Resources and ConocoPhillips has the most
    #    positive recent coverage? Rank all three and cite the documents."
    #
    #   Two kinds of evidence in one ranking — SLB has operational news
    #   (reactivating up to 15 Venezuelan rigs, a Brunei Shell contract),
    #   EOG has three analyst actions pulling in different directions.
    #   Several documents filed under COP are about XOM, CHRD and FANG.
    #
     EvalQuestion(
                             question_id="sentiment_015",
                             question=(
                                  "Which of SLB, EOG Resources and ConocoPhillips has the most "
        "positive recent coverage? Rank all three and cite the documents."
                             ),
                             expected_intent=IntentType.SENTIMENT,
                             expected_tools=["planner", "vector"],
                            reference_answer=(
        "SLB N.V. (SLB) has the most positive recent coverage among the three companies. SLB's coverage highlights operational momentum and international contract wins: SLB was awarded a contract by Brunei Shell Petroleum to support production restoration from shut-in wells across multiple offshore fields, and its valuation coverage reports a 119.7% total return over the past five years with a Discounted Cash Flow estimate pointing to a 41.9% implied discount to the share price.\n\n"
        "ConocoPhillips (COP) ranks second with generally bullish analyst coverage: Morgan Stanley (target raised to $151) and Argus Research (target raised to $153) maintain Overweight/Buy ratings, offset slightly by Barclays lowering its target to $150. COP also hired long-serving Chord Energy executive Shannon Kinney as General Counsel.\n\n"
        "EOG Resources, Inc. (EOG) ranks third with mixed-to-cautious coverage. Although recognized as a decent value pick with strong fundamentals and maintaining an Overweight rating at Wells Fargo ($193 target), analysts at both Barclays ($147 target) and Wells Fargo lowered their price targets, while Morgan Stanley maintained an Equal-Weight rating ($157 target)."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # SLB — SLB N.V.
        "Global energy technology company SLB (NYSE:SLB) today announced it has been awarded a contract by Brunei Shell Petroleum (BSP) to support production restoration from shut-in wells across multiple offshore fields.The",
        "SLB stock has delivered a 119.7% total return over the past "
        "five years, and the current Discounted Cash Flow (DCF) "
        "intrinsic value estimate still points to a sizeable 41.9% "
        "implied discount to the share price, even though market based "
        "valuation multiples look roughly in line with peers. For "
        "investors, that mix raises the question of whether the recent "
        "gains have fully reflected the long term cash flow potential "
        "that the DCF is capturing. Over the past five years SLB has "
        "returned 119.7%,...",

        # COP — ConocoPhillips
        "Morgan Stanley  analyst Devin McDermott   maintains "
        "ConocoPhillips (NYSE:COP) with a Overweight and raises the "
        "price target from $147 to $151.",
        "Argus Research  analyst Bill Selesky   maintains "
        "ConocoPhillips (NYSE:COP) with a Buy and raises the price "
        "target from $136 to $153.",
        "Barclays  analyst Betty Jiang   maintains ConocoPhillips "
        "(NYSE:COP) with a Overweight and lowers the price target from "
        "$155 to $150.",
        "In early August 2026, Chord Energy reported past "
        "second-quarter results showing higher total production "
        "volumes year-on-year, sharply higher revenue of US$2.17 "
        "billion, a swing to net income of US$525.19 million, and "
        "confirmed new production guidance, a US$1.30 per-share base "
        "dividend, and completion of a US$265.92 million buyback "
        "tranche. The company also announced that long-serving "
        "executive Shannon Kinney will depart to become General "
        "Counsel at ConocoPhillips, while CEO Danny Brown...",

        # EOG — EOG Resources, Inc.
        "Morgan Stanley  analyst Devin McDermott   maintains EOG "
        "Resources (NYSE:EOG) with a Equal-Weight and raises the price "
        "target from $156 to $157.",
        "EOG Resources offers a compelling value play with low valuation, strong profitability, solid financial health, and moderate growth potential.",
        "Barclays  analyst Betty Jiang   maintains EOG Resources "
        "(NYSE:EOG) with a Equal-Weight and lowers the price target "
        "from $153 to $147.",
        "Wells Fargo  analyst Sam Margolin   maintains EOG Resources "
        "(NYSE:EOG) with a Overweight and lowers the price target from "
        "$196 to $193."
    ],

    # The order the reference answer argues for.
    expected_ranking=["SLB", "COP", "EOG"],
                             
                             ),
    # sentiment_016   GE BA HON
    #   "Rank GE Aerospace, Boeing and Honeywell by the sentiment of their
    #    recent coverage, and explain what each placement rests on."
    #
    #   Honeywell is the negative anchor — down 51.5% in six months, a
    #   Jefferies Hold, a lowered RBC target — against GE's Air Force
    #   engine award. Both carry political risk in the same set.
    

     EvalQuestion(
                         question_id="sentiment_016",
                         question=(
                             "Rank GE Aerospace, Boeing and Honeywell by the sentiment of their "
       "recent coverage, and explain what each placement rests on."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                        reference_answer=(
        "GE Aerospace (GE) has the most positive recent coverage among the three companies. Its top ranking rests on a significant fair value estimate boost from analysts (shifted from $350.45 to $404.90) following strong Q2 results, intense commercial service demand, strong defense momentum, winning a U.S. Air Force contract with Kratos for the GEK800 engine (JASSM cruise missiles), and a major institutional stake increase from activist investor Nelson Peltz (Trian).\n\n"
        "The Boeing Company (BA) ranks second with moderately positive coverage. Its placement rests on major international defense sales, specifically the U.S. Department of State approving a $4.5 billion possible Foreign Military Sale to Qatar for KC-46A Aerial Refueling Aircraft.\n\n"
        "Honeywell International Inc. (HON) exhibits the weakest coverage sentiment by a wide margin. Its placement rests on severe stock price declines (down 51.5% over 6 months), analyst price target cuts and downgrades (RBC Capital lowering its target to $293; Jefferies assuming a Hold rating with a $255 target), and public admission from Honeywell Aerospace CEO James Currier that a significant share of its 3,000 suppliers underperformed in the first half of the year causing output bottlenecks."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # GE — GE Aerospace
        "Nelson Peltz sharply increased his GE HealthCare stake while "
        "maintaining his sizable GE Aerospace position, according to "
        "Trian&#39;s latest 13F filing.",
        "GE Aerospace and Kratos win a USAF contract for the GEK800 engine powering JASSM missiles. Here’s the latest stock forecast and analysis.",
        "The designation and contract mark advancement of the program "
        "designed to provide small, low-cost, high-performance engines "
        "for use in cruise missiles, collaborative combat-type "
        "aircraft, and other uncrewed aerial",
        "The Fair Value Estimate for General Electric has shifted from "
        "US$350.45 to about US$404.90 per share, which is a meaningful "
        "reset in how analysts are framing the stock. Recent research "
        "following Q2 results and updated guidance links this higher "
        "figure to stronger views on GE Aerospace execution, service "
        "demand and the durability of the current order and backlog "
        "profile. As you read on, you will see how to track this "
        "evolving narrative and what it may mean for your own view on "
        "General...",
        "GE's defense momentum continues as rising demand, major contracts and a strong project pipeline lift revenues, orders and profit.",

        # BA — The Boeing Company
        "https://www.state.gov/releases/bureau-of-political-military-affairs/2026/08/qatar-kc-46a-aerial-refueling-aircraft/",

        # HON — Honeywell International Inc.
        "A significant share of the company's 3,000 suppliers "
        "underperformed in the first half of the year, President and "
        "CEO James Currier said.",
        "RBC Capital  analyst Deane Dray   maintains Honeywell Intl "
        "(NASDAQ:HON) with a Outperform and lowers the price target "
        "from $298 to $293.",
        "Honeywell Technologies faces near-term pressure from weak "
        "demand, rising costs and debt, but automation growth and a "
        "$20B backlog offer support.",
        "Jefferies  analyst Stephen Volkmann   assumes Honeywell Intl "
        "(NASDAQ:HON) with a Hold rating and announces Price Target of "
        "$255."
    ],

    # The order the reference answer argues for.
    expected_ranking=["GE", "BA", "HON"],
                         
                         
                         ),
    # sentiment_017   CAT UPS GE
    #   "Compare recent news sentiment for Caterpillar, UPS and GE
    #    Aerospace. Rank them and support the ranking with the retrieved
    #    documents."
    #
    #   Industrial names pulled into the AI build-out story. The coverage
    #   is about data-centre demand reaching them, not about their own
    #   results.
    

     EvalQuestion(
                         question_id="sentiment_017",
                         question=(
                              "Compare recent news sentiment for Caterpillar, UPS and GE "
        "Aerospace. Rank them and support the ranking with the retrieved "
       "documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                         reference_answer=(
        "GE Aerospace (GE) has the most positive recent coverage sentiment among the three companies. Its top ranking rests on a significant fair value estimate boost from analysts (shifted from $350.45 to $404.90) following strong Q2 results, intense commercial service demand, strong defense momentum, winning a U.S. Air Force contract with Kratos for the GEK800 engine powering JASSM cruise missiles, and an increased stake from activist investor Nelson Peltz (Trian).\n\n"
        "Caterpillar, Inc. (CAT) ranks second with solid positive coverage: historical performance data notes that CAT has outperformed the market over the past 5 years by 21.71% annually (producing a 33.53% average annual return), while recent operational coverage highlights a $3 million workforce initiative launch in Arkansas to prepare workers for modern manufacturing careers.\n\n"
        "United Parcel Service, Inc. (UPS) ranks third with mixed-to-cautious coverage. While analysts remain moderately optimistic and note $3 billion in targeted 2026 network savings alongside tariff refund processing, coverage emphasizes core U.S. volume weakness, below-historical margins, capped growth following its Amazon scale down, and past-year underperformance relative to the broader market leading to a 'HOLD' rating."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # GE — GE Aerospace
        "Nelson Peltz sharply increased his GE HealthCare stake while "
        "maintaining his sizable GE Aerospace position, according to "
        "Trian&#39;s latest 13F filing.",
        "GE Aerospace and Kratos win a USAF contract for the GEK800 engine powering JASSM missiles. Here’s the latest stock forecast and analysis.",
        "The designation and contract mark advancement of the program "
        "designed to provide small, low-cost, high-performance engines "
        "for use in cruise missiles, collaborative combat-type "
        "aircraft, and other uncrewed aerial",
        "The Fair Value Estimate for General Electric has shifted from "
        "US$350.45 to about US$404.90 per share, which is a meaningful "
        "reset in how analysts are framing the stock. Recent research "
        "following Q2 results and updated guidance links this higher "
        "figure to stronger views on GE Aerospace execution, service "
        "demand and the durability of the current order and backlog "
        "profile. As you read on, you will see how to track this "
        "evolving narrative and what it may mean for your own view on "
        "General...",
        "GE's defense momentum continues as rising demand, major contracts and a strong project pipeline lift revenues, orders and profit.",

        # CAT — Caterpillar, Inc.
        "Investment will focus on making training more accessible, "
        "defining what skills are needed for future jobs and "
        "connecting individuals to careers in modern manufacturingThe "
        "Academies of Central Arkansas, University of",
        "Caterpillar (NYSE:CAT) has outperformed the market over the past 5 years by 21.71% on an annualized basis producing an average annual return of 33.53%. Currently, Caterpillar has a market capitalization of $409.17",

        # UPS — United Parcel Service, Inc.
        "United Parcel Service (UPS) is rated HOLD due to ongoing core U.S. volume weakness and margins below historical levels, despite recent topline growth.",
        "UPS is targeting about $3 billion in 2026 network savings as stronger pricing, higher cash flow and cost cuts support margins despite weaker package volumes.",
        "While United Parcel Service has underperformed the broader market over the past year, Wall Street analysts are moderately optimistic about the stock’s prospects.",
        "Shippers including FedEx and UPS that acted as customs brokers for imported packages and received tariff refunds from the U.S. government have started to pass on those refunds to the customers that originally paid the tariffs."
    ],

    # The order the reference answer argues for.
    expected_ranking=["GE", "CAT", "UPS"],
                         
                         ),
    # sentiment_018   NFLX DIS GOOGL
    #   "Rank Netflix, Disney and Alphabet by the sentiment of their
    #    recent coverage, and attribute each piece of evidence to the
    #    company it is about."
    #
    #   The threat to Netflix is in Alphabet's file: YouTube offering
    #   creators millions not to work with Netflix. Reachable here because
    #   GOOGL is in the cohort — worth checking the pipeline attributes it
    #   to the right company rather than reading it as good news for both.
    

     EvalQuestion(
                         question_id="sentiment_018",
                         question=(
                              "Rank Netflix, Disney and Alphabet by the sentiment of their "
        "recent coverage, and attribute each piece of evidence to the "
        "company it is about."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     reference_answer=(
        "Netflix, Inc. (NFLX) exhibits the most positive recent coverage among the three companies. Evidence attributed to Netflix includes a stock price climb after Bill Ackman's Pershing Square took a 4.9% portfolio position signaling double-digit growth and market leadership, stock price rebounds reclaiming key moving averages, 10-year market outperformance (23.1% average annual return), stock recommendations on CNBC's 'Final Trades', and praise for its financial discipline in walking away from distressed deals like Paramount.\n\n"
        "Alphabet Inc. (GOOGL) ranks second with moderately positive to mixed coverage. Evidence attributed to Alphabet includes an aggressive YouTube strategy of offering millions to popular creators for exclusive video uploads to prevent them from cross-posting content with Netflix and protect advertising revenue, offset by short-term stock price pressure as Alphabet shares fell sharply in a Big Tech ETF slump.\n\n"
        "The Walt Disney Company (DIS) ranks third with the most negative coverage. Evidence attributed to Disney focuses on intense regulatory and legal battles, as Disney's ABC filed a First Amendment lawsuit against Trump's FCC alleging an 'extraordinary assault' on free speech and a retaliatory campaign over its programming (including pressure to censor 'The View')."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # NFLX — Netflix, Inc.
        "Netflix stock climbs after Pershing Square takes a 4.9% portfolio position, signaling double-digit growth and market leadership.",
        "Bryn Talkington picked Horizon Kinetics, Stephanie Link chose Elanco Animal Health, and Jason Snipe recommended Netflix.",
        "Netflix Inc (NASDAQ:NFLX) shares are trading higher on Tuesday, extending a recent rebound as the stock works to reclaim key moving averages.",
        "Paramount's motion for a $1.9B bond exposes a balance sheet already in the Altman-Z distress zone. Why Netflix's discipline to walk away looks smarter every week.",
        "Netflix (NASDAQ:NFLX) has outperformed the market over the past 10 years by 9.62% on an annualized basis producing an average annual return of 23.1%. Currently, Netflix has a market capitalization of $319.23 billion.",

        # GOOGL — Alphabet Inc.
        "An exchange-traded fund comprising seven major U.S. tech stocks, the Roundhill Magnificent Seven ETF, experienced a sharp decline on Thursday. Shares of Tesla, Amazon, and Alphabet were notably down, with Tesla suffering the largest loss of over 2%. The ETF's overall slump was recorded at 1.1% according to FactSet data.",
        "YouTube is offering millions to popular creators for exclusive video uploads, aiming to prevent them from simultaneously working with Netflix. This strategy includes direct financing of programs and sharing portions of major brand deals. Netflix has been paying YouTubers to cross-post content, seeking to attract younger audiences and expand its subscriber base, which YouTube views as a threat to its viewership and advertising revenue.",

        # DIS — Walt Disney Company (The)
        "Disney sues Trump’s FCC over alleged ABC retaliation, citing First Amendment violations and pressure to censor ‘The View.’",
        "Disney's ABC has sued the FCC claiming its investigation and early broadcast licenses renewal are a \"retaliatory campaign\" due to its programming."
    ],

    # The order the reference answer argues for.
    expected_ranking=["NFLX", "GOOGL", "DIS"],
                         
                         
                         ),
    # sentiment_019   DIS NFLX META
    #   "Which of Disney, Netflix and Meta has the most positive recent
    #    news coverage? Rank them and cite the documents behind each
    #    placement."
    #
    #   Litigation as sentiment. Disney's ABC is suing the FCC and calling
    #   the probe an assault on free speech, and Meta faces a federal
    #   trial over child safety. Aggression and exposure look alike in a
    #   headline.
    

     EvalQuestion(
                         question_id="sentiment_019",
                         question=(
                             "Which of Disney, Netflix and Meta has the most positive recent "
        "news coverage? Rank them and cite the documents behind each "
        "placement."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                         reference_answer=(
        "Netflix, Inc. (NFLX) has the most positive recent news coverage among the three companies. Its top ranking rests on multiple bullish signals, including stock price gains following Pershing Square taking a 4.9% portfolio position, shares extending a rebound to reclaim key moving averages, 10-year market outperformance (23.1% average annual return), a recommendation on CNBC's 'Final Trades', and praise for financial discipline in avoiding distressed deals like Paramount.\n\n"
        "Meta Platforms, Inc. (META) ranks second with predominantly negative coverage: reports question whether Mark Zuckerberg's 'AI manifesto' is merely a PR move amid stronger AI competitors, while separate coverage notes Meta is facing a major federal trial in California over child safety.\n\n"
        "The Walt Disney Company (DIS) ranks third with negative coverage focused on regulatory and legal conflict, as Disney and its subsidiary ABC filed a First Amendment lawsuit against the FCC alleging a retaliatory campaign and pressure to censor 'The View'."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # NFLX — Netflix, Inc.
        "Netflix stock climbs after Pershing Square takes a 4.9% portfolio position, signaling double-digit growth and market leadership.",
        "Bryn Talkington picked Horizon Kinetics, Stephanie Link chose Elanco Animal Health, and Jason Snipe recommended Netflix.",
        "Netflix Inc (NASDAQ:NFLX) shares are trading higher on Tuesday, extending a recent rebound as the stock works to reclaim key moving averages.",
        "Paramount's motion for a $1.9B bond exposes a balance sheet already in the Altman-Z distress zone. Why Netflix's discipline to walk away looks smarter every week.",
        "Netflix (NASDAQ:NFLX) has outperformed the market over the past 10 years by 9.62% on an annualized basis producing an average annual return of 23.1%. Currently, Netflix has a market capitalization of $319.23 billion.",

        # META — Meta Platforms, Inc.
        "Opening arguments begin today in a major federal trial facing Meta Platforms (META) in California.",
        "Mark Zuckerberg's \"AI manifesto,\" \"The Future is for Everyone,\" outlines a vision of democratized AI and personal superintelligence agents. However, the article questions whether Meta's past actions and current capabilities align with this ambitious vision, particularly concerning its commitment to open-source principles and its standing in the competitive AI landscape. It suggests that Meta's public stance might be more of a PR move to position itself amidst stronger AI contenders.",

        # DIS — Walt Disney Company (The)
        "Disney sues Trump’s FCC over alleged ABC retaliation, citing First Amendment violations and pressure to censor ‘The View.’",
        "Disney's ABC has sued the FCC claiming its investigation and early broadcast licenses renewal are a \"retaliatory campaign\" due to its programming."
    ],

    # The order the reference answer argues for.
    expected_ranking=["NFLX", "META", "DIS"],

                         
                         ),
    # sentiment_020   HD MCD NKE SBUX AMZN
    #   "Rank Home Depot, McDonald's, Nike, Starbucks and Amazon by the
    #    sentiment of their recent coverage, and support the full ordering
    #    with evidence from the retrieved documents."
    #
    #   A five-way sector ranking rather than a three-way one. Longer
    #   cohorts have caught ordering bugs the short ones do not.
    #
    #



    # ---- coverage that is only flows or filings ------------------------
    


     EvalQuestion(
                         question_id="sentiment_020",
                         question=(
                              "Rank Home Depot, McDonald's, Nike, Starbucks and Amazon by the "
       "sentiment of their recent coverage, and support the full ordering "
       "with evidence from the retrieved documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                        reference_answer=(
        "Amazon.com, Inc. (AMZN) has the most positive recent news coverage among the five companies. Its top ranking rests on strong long-term stock performance metrics (outperforming the market over 15 years with an average annual return of 24.36%, turning $1,000 into over $27,000) and securing major commercial contracts, such as Delta Air Lines choosing Amazon's satellite WiFi over Starlink for inflight connectivity.\n\n"
        "The Home Depot, Inc. (HD) ranks second with generally positive coverage. HD reported better-than-expected Q2 earnings with sales beating estimates, 5.7% revenue growth, digital sales momentum, and analyst price target upgrades (such as Mizuho raising its target to $390 and UBS maintaining a Buy rating), despite some noted caution around DIY consumer demand and potential tariff pressures.\n\n"
        "McDonald's Corporation (MCD) ranks third with moderately positive to neutral coverage. Its sentiment is supported by menu innovation and growth strategy execution, specifically highlighting the official addition of energy drinks to its menu through the debut of the Red Bull Dragonberry Energizer.\n\n"
        "Starbucks Corporation (SBUX) ranks fourth with mixed-to-negative coverage. While historical data notes 20-year market outperformance (10.45% average annual return), recent coverage highlights significant headwinds, including shedding over 100 jobs to wrap up restructuring and Starbucks Korea recording its first quarterly loss in 27 years due to a marketing debacle, consumer boycott, public criticism from President Lee Jae Myung, and a police raid.\n\n"
        "NIKE, Inc. (NKE) ranks fifth with the most severe negative coverage. Although one investor noted buying shares after a six-year hiatus, major coverage emphasizes severe technical and financial distress, reporting that NKE stock has erased $200 billion in market cap, crashed nearly 80% from its 2021 peak, and faced Wall Street warnings of a 'Stage 4' technical breakdown."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # AMZN — Amazon.com, Inc.
        "This article highlights the significant returns an investment in Amazon.com stock would have yielded over 15 years. An initial investment of $1,000 in AMZN 15 years ago would now be worth over $27,000, demonstrating the power of compounded returns. Amazon.com has outperformed the market with an average annual return of 24.36% over this period.",
        "Delta Air Lines chose Amazon's satellite WiFi over Starlink for its inflight connectivity, a decision Elon Musk claims will lead to passenger losses. Delta's CEO defends the choice, citing brand integration, while Musk points to passengers switching airlines. Other airlines, however, are adopting Starlink, raising concerns about Delta's competitive position if it doesn't offer comparable WiFi.",

        # HD — Home Depot, Inc. (The)
        "Mizuho  analyst David Bellinger   maintains Home Depot "
        "(NYSE:HD) with a Outperform and raises the price target from "
        "$385 to $390.",
        "HD shares rallied after upbeat Q2 results. Analysts have mixed ratings and price targets, with some noting potential cost pressures.",
        "Home Depot delivered a strong Q2 2026 with 5.7% revenue growth and solid digital sales momentum but remains rangebound. Click here for this HD stock update.",
        "UBS  analyst Michael Lasser   maintains Home Depot (NYSE:HD) "
        "with a Buy and lowers the price target from $430 to $420.",
        "Home Depot (HD) reports better-than-expected Q2 earnings with sales above estimates. Analysts maintain Buy rating and raise price targets.",

        # MCD — McDonald's Corporation
        "McDonald's (MCD) officially added energy drinks to its menu for the first time today with the debut of its new Red Bull Dragonberry Energizer.",
        "Part of the company's growth strategy is to add interesting menu items while simplifying operations.",

        # SBUX — Starbucks Corporation
        "Starbucks (NASDAQ:SBUX) has outperformed the market over the past 20 years by 1.11% on an annualized basis producing an average annual return of 10.45%. Currently, Starbucks has a market capitalization of $125.56",
        "https://www.bloomberg.com/news/articles/2026-08-20/starbucks-sheds-more-than-100-jobs-as-it-wraps-up-restructuring",
        "Starbucks Korea posted its first quarterly loss since it started operations 27 years ago after a marketing debacle triggered a boycott, criticism from President Lee Jae Myung, and a police raid of its corporate offices.",

        # NKE — NIKE, Inc.
        "Nike stock has erased $200B in market cap since 2021. Read "
        "why Arvy&#39;s CIO warns NKE faces a severe &#39;Stage 4&#39; "
        "technical decline.",
        "Why I Bought Nike After A 6-Year Hiatus"
    ],

    # The order the reference answer argues for.
    expected_ranking=["AMZN", "HD", "MCD", "SBUX", "NKE"],
                         
                         ),
    # sentiment_021   BLK SCHW GS
    #   "Rank BlackRock, Charles Schwab and Goldman Sachs by the sentiment
    #    of their recent coverage and explain the evidence behind the
    #    order."
    #
    #   Almost nothing here is editorial: German WpHG stake notifications,
    #   13F purchases, an iShares Bitcoin Trust minimum cut. Does the
    #   pipeline treat "a fund bought shares" as positive sentiment?
    

     EvalQuestion(
                         question_id="sentiment_021",
                         question=(
                              "Rank BlackRock, Charles Schwab and Goldman Sachs by the sentiment "
       "of their recent coverage and explain the evidence behind the "
       "order."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],

                        reference_answer=(
        "The Charles Schwab Corporation (SCHW) has the most positive recent news coverage among the three firms. SCHW reported strong Q2 2026 earnings beating analyst expectations ($1.62 EPS, $7.07 billion revenue), trades near its 12-month high with an elevated fair value estimate of $125.00, and received massive institutional investment, including a $987.93 million new position from Flossbach Von Storch SE.\n\n"
        "The Goldman Sachs Group, Inc. (GS) ranks second with strong positive coverage. Goldman Sachs reported strong quarterly earnings exceeding analyst estimates, increased its quarterly dividend to $5.00 per share (2.0% yield), maintains a 'Moderate Buy' consensus rating with an average price target of $1,062.86, and secured multimillion-dollar new stakes from institutional investors like Lynch Asset Management ($10.66 million) and M3 Wealth Management ($3.55 million).\n\n"
        "BlackRock, Inc. (BLK) ranks third with moderately positive product and operational coverage. BlackRock significantly expanded accessibility and liquidity by lowering the in-kind conversion minimum for its iShares Bitcoin Trust from $25 million to $1 million, while regulatory filings detailed routine adjustments to its major equity positions in European companies like adidas AG (6.91%) and Commerzbank AG (4.52%)."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # SCHW — The Charles Schwab Corporation
        "Charles Schwab stock is trading near its 12-month high, supported by strong second-quarter 2026 earnings and an updated fair value estimate of $125.00, which is above its current share price of $110.85. The company reported adjusted earnings of $1.62 per share and revenue of $7.07 billion, both exceeding analyst expectations, with robust net margins and return on equity. Institutional interest and a consistent dividend policy further bolster investor confidence in the stock's valuation.",
        "Notis McConarty Edward recently acquired a new stake in The Charles Schwab Corporation, purchasing 36,470 shares valued at approximately $3.365 million. This investment makes Charles Schwab the 26th largest holding for Notis McConarty Edward, comprising 1.5% of its total holdings. The article also details recent insider selling activity and other institutional investor movements, alongside key headlines impacting the company's performance and analyst ratings.",
        "Great Lakes Advisors LLC recently purchased a new stake of $7.20 million in The Charles Schwab Corporation (NYSE:SCHW) during the second quarter. Other institutional investors like BlackRock and Danske Bank also increased their holdings, with institutional ownership now at 84.38%. Charles Schwab reported strong Q2 earnings, exceeding expectations with $1.62 EPS and $7.07 billion in revenue, and analysts maintain a \"Moderate Buy\" rating with an average price target of $121.17.",
        "Flossbach Von Storch SE has made a significant new investment in The Charles Schwab Corporation, purchasing over 10.7 million shares valued at approximately $987.93 million, making it their sixth-largest holding.",
        "Institutional investors collectively own 84.38% of Charles Schwab's stock, and analysts have set a consensus price target of $121.17, with most rating it a \"Buy\" or \"Strong Buy.\" The article also notes recent positive developments for Charles Schwab, such as increased client assets and strong earnings, alongside some insider selling and valuation concerns.",

        # GS — Goldman Sachs Group, Inc. (The)
        "Lynch Asset Management Inc. has acquired a new stake in The Goldman Sachs Group, Inc. worth approximately $10.66 million, making it their ninth-largest holding. This investment comes as Goldman Sachs reports strong quarterly earnings, beating analyst estimates, and increasing its quarterly dividend. The company maintains a \"Moderate Buy\" consensus rating from analysts, with institutional investors owning a significant portion of its stock.",
        "M3 Wealth Management LLC acquired 3,508 shares of The Goldman Sachs Group, Inc. (GS) worth approximately $3.55 million, making it their 17th-largest holding. Goldman Sachs recently reported strong quarterly earnings, surpassing analyst estimates, and increased its quarterly dividend to $5.00 per share, yielding 2.0%. Analysts maintain a \"Moderate Buy\" rating with an average price target of $1,062.86.",

        # BLK — BlackRock, Inc.
        "adidas AG has published a release in accordance with Article 40, Section 1 of the German Securities Trading Act (WpHG) regarding a notification of major holdings. BlackRock, Inc. has reported a change in its total positions in adidas AG, showing 6.57% voting rights attached to shares and 0.34% through instruments, totaling 6.91%. This notification details a voluntary group notification due to a triggered threshold at the subsidiary level, with the threshold being crossed on August 14, 2026.",
        "BlackRock has significantly lowered the minimum requirement for in-kind conversions of its iShares Bitcoin Trust from $25 million to $1 million. This strategic move aims to broaden accessibility for smaller investors, allowing them to convert shares directly into Bitcoin more easily. The change is expected to increase the trust's liquidity and attract a wider range of participants to BlackRock's Bitcoin investment offerings.",
        "Commerzbank AG has released a notification of major holdings according to Article 40, Section 1 of the WpHG. BlackRock, Inc. has acquired voting rights in Commerzbank, crossing a threshold on August 17, 2026. The new total position for BlackRock is 4.52%, comprising 3.01% voting rights attached to shares and 1.51% through instruments."
    ],

    # The order the reference answer argues for.
    expected_ranking=["SCHW", "GS", "BLK"],
                         
                         
                         ),
    # sentiment_022   JNJ PFE UNH
    #   "Which of Johnson & Johnson, Pfizer and UnitedHealth has the most
    #    positive recent news coverage? Rank them and cite the documents."
    #
    #   Flows that disagree inside one name — two funds selling J&J,
    #   another buying — while UnitedHealth's coverage is flatly neutral
    #   and Pfizer's is a settlement of about 5,000 federal claims.
    

     EvalQuestion(
                         question_id="sentiment_022",
                         question=(
                            "Which of Johnson & Johnson, Pfizer and UnitedHealth has the most "
            "positive recent news coverage? Rank them and cite the documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],

                     reference_answer=(
        "Johnson & Johnson (JNJ) has the most positive recent news coverage among the three companies. JNJ reported strong Q2 earnings that beat expectations ($2.90 EPS, $25.31 billion revenue), raised its fiscal 2026 EPS guidance, maintained a 'Moderate Buy' rating ($268.22 target), and received praise for community contributions including a $300,000 grant to modernize the Rutgers-Camden nursing lab.\n\n"
        "UnitedHealth Group Incorporated (UNH) ranks second with strong positive coverage: UNH reported robust Q2 earnings beating expectations ($6.38 EPS), reaffirmed its fiscal 2026 EPS guidance, declared a $2.32 quarterly dividend, and holds a 'Moderate Buy' consensus ($455.92 target), though its stock trades below its recent peak and faces minor regulatory risks.\n\n"
        "Pfizer, Inc. (PFE) ranks third with the weakest coverage sentiment. While PFE beat Q2 earnings ($0.77 EPS, $15.03B revenue) and shows potential in its obesity drug pipeline, analysts maintain an average 'Hold' rating due to a looming patent cliff and significant litigation uncertainty surrounding a settlement program to resolve 5,000 federal lawsuits regarding Depo-Provera."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # JNJ — Johnson & Johnson
        "Vest Financial LLC significantly reduced its stake in Johnson "
        "& Johnson (JNJ) by selling 103,567 shares in the second "
        "quarter, although it still retains a substantial holding "
        "worth approximately $65.8 million. This comes as Johnson & "
        "Johnson reported strong quarterly results, exceeding revenue "
        "and EPS expectations, and increased its fiscal 2026 EPS "
        "guidance. Analysts generally maintain a \"Moderate Buy\" rating "
        "for JNJ, citing its defensive growth characteristics and "
        "consistent dividend increases.",
        "Johnson & Johnson has donated $300,000 to modernize the simulation lab at Rutgers School of Nursing-Camden, now named in the company's honor. This funding has allowed the purchase of advanced patient simulators and AI-enabled technologies for hands-on student training. The donation also supports electronic medical record training, a pharmacology lab, and five $10,000 scholarships for first-generation nursing students.",
        "Johnson & Johnson reported strong quarterly earnings, beating expectations with $2.90 EPS and $25.31 billion in revenue, and declared a quarterly dividend of $1.34 per share, while analysts maintain a \"Moderate Buy\" rating with a target price of $268.22.",

        # UNH — UnitedHealth Group Incorporated
        "UnitedHealth Group stock is trading below its recent peak despite the S&P 500 healthcare sector reaching a record high, driven by strong investor appetite. The company's diverse operations, including UnitedHealthcare insurance and the Optum services platform, along with its consistent dividend stream, support its position as a key player in the healthcare market.",
        "Simplicity Wealth LLC significantly increased its stake in UnitedHealth Group (UNH) by 156.7% in Q2, bringing its total holdings to 31,667 shares valued at $13.2 million. Institutional investors and hedge funds collectively own 87.86% of the company, and analysts maintain a \"Moderate Buy\" rating with an average price target of $455.92. UnitedHealth also reported strong quarterly EPS of $6.38, exceeding estimates, and declared a quarterly dividend of $2.32 per share.",
        "Plato Investment Management Ltd increased its stake in "
        "UnitedHealth Group (UNH) by 26.6%, purchasing an additional "
        "4,863 shares to bring its total holdings to 23,178 shares "
        "valued at $9.6 million. UnitedHealth reported strong Q2 "
        "earnings, exceeding revenue and EPS estimates, and reaffirmed "
        "its fiscal 2026 EPS guidance. Analysts generally maintain a "
        "\"Moderate Buy\" rating for UNH, despite the stock opening "
        "lower and facing regulatory risks.",

        # PFE — Pfizer, Inc.
        "Janney Montgomery Scott LLC has increased its stake in Pfizer Inc. by 3.4% during the second quarter, bringing its total holdings to 2.41 million shares valued at approximately $58.14 million. Pfizer recently reported strong quarterly earnings of $0.77 per share and revenue of $15.03 billion, surpassing analyst expectations, and declared a quarterly dividend of $0.43 per share.",
        "Despite an average \"Hold\" rating from analysts and concerns about a looming patent cliff, the stock is showing positive sentiment due to pipeline developments and unusual call-option activity.",
        "Pfizer (NYSE:PFE) has established a settlement program aimed at resolving a significant portion of federal lawsuits concerning Depo-Provera intracranial meningioma, potentially covering around 5,000 of over 6,200 pending claims. This confidential agreement is a crucial legal development that could impact Pfizer's litigation reserves, risk profile, and public perception."
    ],

    # The order the reference answer argues for.
    expected_ranking=["JNJ", "UNH", "PFE"],
                         
                         
                         ),
    # sentiment_023   WFC C GS
    #   "Rank Wells Fargo, Citigroup and Goldman Sachs by the sentiment of
    #    their recent coverage. Say how much evidence each placement rests
    #    on."
    #
    #   Genuinely thin coverage, two to four chunks each. The honest
    #   answer states how little there is; the failure mode is a confident
    #   ranking built on a Citi note about Cactus.
    #
     EvalQuestion(
                         question_id="sentiment_023",
                         question=(
                              "Rank Wells Fargo, Citigroup and Goldman Sachs by the sentiment of "
        "their recent coverage. Say how much evidence each placement rests "
       "on."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                        reference_answer=(
        "The Goldman Sachs Group, Inc. (GS) has the most positive recent coverage sentiment among the three firms, resting on strong financial performance and analyst backing. GS reported strong Q2 earnings that surpassed analyst estimates, increased its quarterly dividend to $5.00 per share (2.0% yield), maintains a 'Moderate Buy' consensus rating with an average price target of $1,062.86, and secured multimillion-dollar new investments from Lynch Asset Management ($10.66M) and M3 Wealth Management ($3.55M).\n\n"
        "Citigroup Inc. (C) ranks second with moderately positive operational and analytical coverage, though it rests on a smaller amount of direct evidence (two chunks). Citi adopted Ant International's upgraded forex AI tool to enhance its foreign exchange operations, while its research division issued an updated price target increase ($67 to $75) for Cactus Inc.\n\n"
        "Wells Fargo & Company (WFC) ranks third with coverage pointing strongly both ways across four detailed chunks. On the positive side, WFC delivered a 122.1% three-year return, reported strong Q2 financial results, and screens as 26.5% undervalued under excess return models. However, its sentiment is heavily weighed down by ongoing workforce reductions—cutting 14 additional jobs in West Des Moines (bringing total local cuts to 1,619 across 103 rounds since 2022) as CEO Charlie Scharf slims down the bank amid regulatory pressure and home mortgage weakness."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # GS — Goldman Sachs Group, Inc. (The)
        "Lynch Asset Management Inc. has acquired a new stake in The Goldman Sachs Group, Inc. worth approximately $10.66 million, making it their ninth-largest holding. This investment comes as Goldman Sachs reports strong quarterly earnings, beating analyst estimates, and increasing its quarterly dividend. The company maintains a \"Moderate Buy\" consensus rating from analysts, with institutional investors owning a significant portion of its stock.",
        "M3 Wealth Management LLC acquired 3,508 shares of The Goldman Sachs Group, Inc. (GS) worth approximately $3.55 million, making it their 17th-largest holding. Goldman Sachs recently reported strong quarterly earnings, surpassing analyst estimates, and increased its quarterly dividend to $5.00 per share, yielding 2.0%. Analysts maintain a \"Moderate Buy\" rating with an average price target of $1,062.86.",

        # C — Citigroup Inc.
        "Banks including Barclays, Citi, Deutsche Bank, and Standard Chartered have adopted an upgraded foreign exchange AI tool developed by Ant International. Ant International is an overseas affiliate and spin-out of Ant Group. This adoption signifies a move by major financial institutions to leverage advanced AI in forex operations.",
        "Cactus (WHD) shares fell following a downgrade by Citigroup "
        "from Buy to Neutral. Despite the downgrade, Citigroup "
        "increased its price target for Cactus to $75 from $67. The "
        "article also lists recent insider share sales for Cactus, "
        "indicating significant transaction activity by company "
        "insiders in early August.",

        # WFC — Wells Fargo & Company
        "Wells Fargo announced another round of layoffs, cutting 14 jobs at its Jordan Creek campus in West Des Moines, bringing the total for the year to 322 in the Des Moines metro. Since April 2022, the bank has eliminated 1,619 jobs in the area through 103 rounds of layoffs, as CEO Charlie Scharf continues to slim down the workforce amid industry changes.",
        "This follows strong second-quarter financial results but reflects ongoing adjustments to market conditions and regulatory pressure, particularly impacting its home mortgage division.",
        "Wells Fargo (WFC) stock, despite a 122.1% return over the past three years, continues to trade below its estimated intrinsic value based on the Excess Returns model and earnings multiples. While recent investor interest in bank stocks has narrowed the valuation gap, the stock screens as undervalued by 26.5% according to the Excess Returns analysis and also appears undervalued based on its P/E multiple compared to a tailored Fair Ratio benchmark.",
        "The key question for investors is whether this discount reflects genuine opportunity or persistent concerns about sector risks like interest rates and credit quality."
    ],

    # The order the reference answer argues for.
    expected_ranking=["GS", "C", "WFC"],
                         
                         ),


    # ---- ambiguity a human has to resolve ------------------------------
    #
    # sentiment_024   PYPL INTC BAC
    #   "Rank PayPal, Intel and Bank of America by the sentiment of their
    #    recent news coverage, and explain how you read any coverage that
    #    cuts both ways."
    #
    #   Takeover speculation and concentration both cut two ways. PayPal
    #   is talked about as a Stripe/Advent target while Truist holds at
    #   $62; Intel is 67% of SoftBank's U.S. book without SoftBank buying
    #   a share; Bank of America is held with the price already requiring
    #   a 16% terminal ROTCE.
    

     EvalQuestion(
                         question_id="sentiment_024",
                         question=(
                                "Rank PayPal, Intel and Bank of America by the sentiment of their "
                                    "recent news coverage, and explain how you read any coverage that "
                                   "cuts both ways."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                         reference_answer=(
        "PayPal Holdings, Inc. (PYPL) has the most positive recent coverage sentiment overall. PYPL coverage highlights a 'Strong Buy' rating driven by reports of renewed takeover talks with Stripe and Advent, major commercial expansion into college tuition payments through integrations with Illumia, Nelnet Campus Commerce, and TouchNet (live at major universities), inclusion in turnaround bets by prominent investors (Tom Hayes), and a price target increase to $62 from Truist Securities.\n\n"
        "Intel Corporation (INTC) ranks second with coverage that cuts both ways. On the positive side, coverage highlights SoftBank Group's massive vote of confidence (Intel making up 67% of its U.S. portfolio at $12.1 billion) as the stock nearly tripled in a single quarter following strategic AI and foundry roadmap shifts. However, this is cut by coverage noting that SoftBank bought zero new shares last quarter, Intel's business performance is recovering slowly, valuation remains expensive, and the stock faces dilution from its own share offerings.\n\n"
        "Bank of America Corporation (BAC) ranks third with mixed-to-cautious coverage. On the positive side, BAC reported strong Q2 financial results (net income up 27%, diluted EPS up 34%) and outperformance relative to the equity market. However, coverage cuts this momentum by assigning a 'Hold' rating—explaining that current share prices already price in a steep 16% terminal ROTCE and warning investors not to chase short-term bond market momentum—while 13F filings revealed that Warren Buffett's Berkshire Hathaway trimmed its BAC position."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # PYPL — PayPal Holdings, Inc.
        "Investor Tom Hayes warns Berkshire Hathaway is "
        "&#34;done.&#34; Discover why he&#39;s betting big on "
        "turnaround stocks like PayPal and Intel instead.",
        "PayPal is reportedly back in takeover talks with Stripe and Advent, with expectations for an improved acquisition offer. Read why PYPL stock is a Strong Buy.",
        "PayPal (Nasdaq: PYPL) today announced new integrations with three of the nation's leading education payment platforms, Illumia, Nelnet Campus Commerce, and TouchNet, that give students and their families the option to pay tuition and fees directly with PayPal or Venmo. These integrations are live at schools across the nation, including Bellarmine University, Butler University, Kansas State University, Michigan State University, and Texas Tech University, with more institutions expected to join t",
        "Truist Securities  analyst Matthew Coad   maintains PayPal "
        "Holdings (NASDAQ:PYPL) with a Hold and raises the price "
        "target from $59 to $62.",

        # INTC — Intel Corporation
        "SoftBank Group has made Intel (NasdaqGS: INTC) the largest component of its U.S. equity portfolio, with the stock representing nearly 67% of its disclosed holdings. This significant concentration signals a strong vote of confidence from SoftBank in Intel's AI and foundry roadmap, aligning with Intel's recent strategic shifts and capital raises.",
        "SoftBank Group's latest 13F filing reveals that Intel (INTC) now constitutes 67% of its U.S. stock portfolio, valued at $12.1 billion as of June 30. However, this high concentration is due to Intel's stock nearly tripling in the last quarter, not new purchases by Masayoshi Son, as SoftBank held the exact same number of shares.",
        "The article notes that while Intel's business performance is improving, the stock's valuation still appears expensive, especially given its recent price drop and the dilution from Intel's own share offering.",

        # BAC — Bank of America Corporation
        "Bank of America delivered robust Q2 results, with net income up 27% and diluted EPS up 34%, driven by broad revenue growth. Read why BAC stock is a Hold.",
        "Bank of America is outperforming the already elevated equity market YTD as credit conditions change. Read more on BAC stock here.",
        "Berkshire Hathawayâs Q2 2026 13F: portfolio hits ~$299B as "
        "Buffett adds Alphabet & trims BACâsee top holdings, key "
        "moves, and buyback details now." ],

    # The order the reference answer argues for.
    expected_ranking=["PYPL", "INTC", "BAC"],        
                         
                         ),
    # sentiment_025   BMY ABBV JNJ
    #   "Which of Bristol Myers Squibb, AbbVie and Johnson & Johnson has
    #    the most positive recent coverage? Rank them and support the
    #    ranking with the retrieved documents."
    #
    #   Bristol Myers has an FDA accelerated approval and a revived $6.7B
    #   lawsuit. AbbVie raised $9B of debt to fund an acquisition — growth
    #   or leverage, depending on who is reading.
    

     EvalQuestion(
                         question_id="sentiment_025",
                         question=(
                              "Which of Bristol Myers Squibb, AbbVie and Johnson & Johnson has "
        "the most positive recent coverage? Rank them and support the "
        "ranking with the retrieved documents."
                         ),
                         expected_intent=IntentType.SENTIMENT,
                         expected_tools=["planner", "vector"],
                     
                        reference_answer=(
        "Johnson & Johnson (JNJ) has the most positive recent coverage sentiment among the three pharmaceutical giants. JNJ reported strong Q2 earnings beating analyst expectations ($2.90 EPS, $25.31 billion revenue), raised its fiscal 2026 EPS guidance, maintained a 'Moderate Buy' analyst consensus ($268.22 price target), and received positive community coverage for donating $300,000 to modernize the simulation lab at Rutgers School of Nursing-Camden.\n\n"
        "AbbVie Inc. (ABBV) ranks second with strong overall operational coverage: ABBV reported strong Q2 earnings surpassing expectations ($3.65 EPS, $16.99 billion revenue), trades at the top of its 52-week range driven by regulatory momentum for SKYRIZI in Crohn's disease, and holds analyst 'Buy' / 'Moderate Buy' ratings with price targets up to $300. However, its sentiment is slightly tempered by a $9 billion debt offering to acquire Apogee Therapeutics and a sharp revenue drop reported by partner GUBRA due to the absence of a one-time deal.\n\n"
        "Bristol-Myers Squibb Company (BMY) ranks third with mixed coverage. On the positive side, BMY secured U.S. FDA accelerated approval for ZENBEXUS (iberdomide) in multiple myeloma (marking the first CELMoD therapy approval) and achieved progress under its RNA collaboration with Atrium Therapeutics. However, its coverage is heavily burdened by negative news, including an appeals court reviving a $6.7 billion lawsuit against BMY on behalf of former Celgene shareholders and cooling rumors surrounding a potential $400 billion merger with AstraZeneca."
    ),

    # VERBATIM from document_chunks.
    reference_contexts=[
        # JNJ — Johnson & Johnson
        "Vest Financial LLC significantly reduced its stake in Johnson "
        "& Johnson (JNJ) by selling 103,567 shares in the second "
        "quarter, although it still retains a substantial holding "
        "worth approximately $65.8 million. This comes as Johnson & "
        "Johnson reported strong quarterly results, exceeding revenue "
        "and EPS expectations, and increased its fiscal 2026 EPS "
        "guidance. Analysts generally maintain a \"Moderate Buy\" rating "
        "for JNJ, citing its defensive growth characteristics and "
        "consistent dividend increases.",
        "Johnson & Johnson has donated $300,000 to modernize the simulation lab at Rutgers School of Nursing-Camden, now named in the company's honor. This funding has allowed the purchase of advanced patient simulators and AI-enabled technologies for hands-on student training. The donation also supports electronic medical record training, a pharmacology lab, and five $10,000 scholarships for first-generation nursing students.",
        "Johnson & Johnson reported strong quarterly earnings, beating expectations with $2.90 EPS and $25.31 billion in revenue, and declared a quarterly dividend of $1.34 per share, while analysts maintain a \"Moderate Buy\" rating with a target price of $268.22.",

        # ABBV — AbbVie Inc.
        "Vest Financial LLC reduced its stake in AbbVie Inc. by 1.4% "
        "in the second quarter, selling 3,946 shares and retaining "
        "268,319 shares valued at approximately $67.5 million. Other "
        "institutional investors have also adjusted their positions, "
        "and institutional ownership collectively stands at 70.23% of "
        "ABBV. Additionally, AbbVie reported strong quarterly "
        "earnings, exceeding expectations with $3.65 EPS and $16.99 "
        "billion in revenue, while maintaining a $1.73 quarterly "
        "dividend.",
        "AbbVie recently completed a $9 billion debt offering consisting of unsecured senior notes maturing between 2028 and 2066. The primary purpose of this debt issuance is to finance its acquisition of Apogee Therapeutics, with a provision for redemption if the deal falls through. Analysts currently rate ABBV stock as a Buy with a $300 price target, though TipRanks' AI Analyst, Spark, identifies it as Neutral due to strong cash generation offset by high debt.",
        "AbbVie (ABBV) stock is trading at the top of its 52-week range, driven by the potential for a new subcutaneous induction option for its immunology drug SKYRIZI in Crohn's disease, which is currently under regulatory review. This dosing change is expected to accelerate SKYRIZI sales, a drug that already accounts for nearly a third of AbbVie's guided revenue and has seen its sales forecast raised twice this year.",
        "GUBRA experienced a sharp decline in revenue and profit "
        "year-over-year due to the absence of a significant one-time "
        "deal with AbbVie. Despite this, the company maintained "
        "operational momentum through new clinical trials, growth in "
        "its Contract Research Organization (CRO) services, and the "
        "launch of Gubra Ventures, while continuing to invest in R&D "
        "and infrastructure.",

        # BMY — Bristol-Myers Squibb Company
        "Rumors of an AstraZeneca PLC-Bristol-Myers Squibb Company merger are cooling. Click here for risks and drug portfolio insights on BMY and AZN stock.",
        "PRINCETON, N.J., August 13, 2026--U.S. FDA Grants Accelerated Approval to Bristol Myers Squibb's First CELMoD Therapy ZENBEXUS",
        "A unanimous 3-judge panel ruled that UMB Bank had standing to represent former Celgene shareholders despite a procedural error in its appointment",
        "Bristol Myers Squibb (NYSE:BMY) today announced that the U.S. "
        "Food and Drug Administration (FDA) has approved ZENBEXUS™ "
        "(iberdomide) in combination with "
        "daratumumabandhyaluronidase-fihj and dexamethasone (ZDd) for "
        "the",
        "Atrium Therapeutics, Inc. (Nasdaq: RNA) (\"Atrium,\" \"Atrium Therapeutics,\" or the \"Company\"), a biopharmaceutical company advancing precision cardiology by developing RNA therapeutics targeted to the heart, today reported financial results for the second quarter ended June 30, 2026, and highlighted recent corporate progress including FDA clearance of its Investigational New Drug (IND) application for ATR 1072 and continued achievements under its collaboration with Bristol Myers Squibb (BMS)."
    ],

    # The order the reference answer argues for.
    expected_ranking=["JNJ", "ABBV", "BMY"],
                         
                         ),
    # sentiment_026   BAC JPM MA
    #   "Rank Bank of America, JPMorgan and Mastercard by the sentiment of
    #    their recent coverage, and say which evidence is about the
    #    company itself."
    #
    #   Coverage about conditions rather than companies: the global bond
    #   rout, a 1.26% card delinquency rate, Berkshire and Pershing Square
    #   position changes. Ranking these means deciding whether macro
    #   exposure is sentiment about the bank.
    # ------------------------------------------------------------------


     EvalQuestion(
        question_id="sentiment_026",
        question=(
            "Rank Bank of America, JPMorgan and Mastercard by the sentiment of "
            "their recent coverage, and say which evidence is about the "
            "company itself."
        ),
        expected_intent=IntentType.SENTIMENT,
        expected_tools=["planner", "vector"],
        reference_answer=(
            "JPMorgan Chase & Co. (JPM) and Mastercard Incorporated (MA) display the most positive overall recent coverage sentiment, followed by Bank of America Corporation (BAC).\n\n"
            "JPMorgan Chase & Co. (JPM) ranks first with strong positive coverage directly about the company itself, highlighting long-term market outperformance, a bullish projection from Wells Fargo stating JPM could become the first $1 trillion bank and double again in 7-8 years, and being selected by General Atlantic to lead a fresh IPO push.\n\n"
            "Mastercard Incorporated (MA) ranks second with strong positive coverage directly about the company itself, featuring high-profile institutional buying from Bill Ackman's Pershing Square (citing its dominant network status and compressed valuation), strong-growth screen validation with a bullish technical breakout setup, leadership expansion in its EEMA unit, and new strategic partnerships across crypto stablecoins (Borderless.xyz), merchant cloud services (Fiserv), and co-branded cards (American Airlines, Citi).\n\n"
            "Bank of America Corporation (BAC) ranks third with mixed-to-cautious coverage directly about the company itself. While BAC reported robust Q2 financial results (net income up 27%, diluted EPS up 34%) and outperformance YTD, analysts maintain a 'Hold' rating (noting the current price already requires a steep 16% terminal ROTCE) and 13F filings revealed that Berkshire Hathaway trimmed its BAC position."
        ),
        reference_contexts=[
            # JPM — JP Morgan Chase & Co.
            "JPMorgan Chase (NYSE:JPM) has outperformed the market over the past 5 years by 6.71% on an annualized basis producing an average annual return of 18.46%. Currently, JPMorgan Chase has a market capitalization of $959.71",
            "https://www.bloomberg.com/news/articles/2026-08-17/general-atlantic-is-said-to-tap-jpmorgan-to-lead-fresh-ipo-push",
            "Wells Fargo says JPMorgan could become the first $1 trillion bank, with potential to double its market cap within 7-8 years.",

            # MA — Mastercard Incorporated
            "Mastercard: A Rare Growth Stock I'm Comfortable Buying At 28.5x Earnings",
            "In recent days, Mastercard’s Eastern Europe, Middle East and Africa unit named 20-year company veteran Yasemin Bedir as its next president effective September 1, 2026, while the company also expanded collaborations ranging from crypto-compliant cross-border stablecoin payments with Borderless.xyz to merchant cloud services with Fiserv and enhanced co-branded card benefits with American Airlines and Citi. At the same time, Bill Ackman’s Pershing Square has disclosed a new position in...",
            "Discover why Mastercard (NYSE:MA) passes a strong-growth screen with solid fundamentals and a bullish technical breakout setup for potential entry.",
            "Pershing Square initiated positions in Visa and Mastercard, citing their dominant network status. Read the full analysis for more details.",

            # BAC — Bank of America Corporation
            "Bank of America delivered robust Q2 results, with net income up 27% and diluted EPS up 34%, driven by broad revenue growth. Read why BAC stock is a Hold.",
            "Bank of America is outperforming the already elevated equity market YTD as credit conditions change. Read more on BAC stock here.",
            "- SEC Filing",
            "Berkshire Hathawayâs Q2 2026 13F: portfolio hits ~$299B as "
            "Buffett adds Alphabet & trims BACâsee top holdings, key "
            "moves, and buyback details now."
        ],
        expected_ranking=["JPM", "MA", "BAC"],
    ),
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

# The SENTIMENT representative in the smoke set.
#
# sentiment_001 stood here until 2026-08-22. It was the authored
# sentiment_002 word for word, with the same expected_ranking, so it was
# removed rather than kept as a duplicate — a second copy measures one
# question twice and weights it double in any set holding both.
#
# sentiment_002 replaces it on merit as well as by default: two reference
# contexts, the fewest in the set, so it is the cheapest question here to
# run, and it scored highest of the twenty-five in the 2026-08-21 baseline
# at 0.937 overall with 0.714 context_entity_recall. A change that
# regresses retrieval shows up against a high, stable number.
SMOKE: list[EvalQuestion] = [
    q for q in AUTHORED if q.question_id == "sentiment_002"
]


QUESTIONS = AUTHORED
