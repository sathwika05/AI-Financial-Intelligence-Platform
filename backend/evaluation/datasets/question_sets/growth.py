"""
The growth set: growth questions, generated from the database.

ORIGINALS holds the hand-written question that predates the generator. It
is deliberately NOT counted in QUESTIONS: it asks the same thing as one of
the generated questions, so counting both would weight it double in the
pass rate. It still runs, in the smoke set.
"""
from backend.evaluation.schemas import EvalQuestion, IntentType
from backend.evaluation.datasets.question_sets._generated import _load_generated


ORIGINALS: list[EvalQuestion] = [
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



GENERATED = _load_generated("growth")

QUESTIONS = GENERATED
