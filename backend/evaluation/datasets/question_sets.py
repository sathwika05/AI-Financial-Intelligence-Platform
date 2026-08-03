


from backend.evaluation.schemas import EvalQuestion, IntentType


VALUATION_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question_id= "valaution_001",
        question = (
            "Which five technology companies have the lowest P/E"
            "ratios and positive earnings?"
        ),
        expected_intent=IntentType.VALUATION,
        expected_tools = ["sql"],
        expected_keywords = [
            "P/E",
            "earnings",
            "valuation",
        ],
    ),
]

GROWTH_QUESTIONS: list[EvalQuestion] =[
    EvalQuestion(
        question_id="growth_001",
        question = (
            "Rank the five companies with the strongest revenue"
            "and EPS growth"
        ),
        expected_intent=IntentType.GROWTH,
        expected_tools=["sql"],
        expected_keywords=[
            "revenue growth",
            "EPS growth",
        ],
    ),
]

SENTIMENT_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question_id="sentiment_001",
        question = (
            "Which semiconductor companies have the most positive"
            "sentiment in recent earnings reports?"
        ),
        expected_intent=IntentType.SENTIMENT,
        expected_tools = ["vector"],
        expected_keywords = [
            "sentiment",
            "earnings",
        ],
        reference_answer = (
            "The answer should rank semiconductor companies using"
            "evidence retrieved from earnings-related documents."
        ),
    ),
]

MIXED_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question_id="mixed_001",
        question=(
            "Rank the best AI- related stocks using valuation, "
            "growth, market performance, and document sentiment."
        ),
        expected_intent=IntentType.MIXED,
        expected_tools=[
            "sql",
            "vector",
            "market",
        ],
        expected_keywords = [
            "valuation",
            "growth",
            "sentiment",
            "market",
        ],
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

def get_question_set(name: str) -> list[EvalQuestion]:
    normalized = name.strip().lower()

    if normalized not in QUESTION_SETS:
        supported = ", ".join(sorted(QUESTION_SETS))
        raise ValueError(
            f"Unknown question set '{name}'. Supported: {supported}"
        )

    return QUESTION_SETS[normalized]