import logging

logger = logging.getLogger(__name__)


def normalize_0_to_1(
    value:     float,
    min_val:   float,
    max_val:   float,
    inverse:   bool = False
) -> float:
    """
    Generic normalization to 0-1 scale.

    inverse=False → higher value = higher score
    inverse=True  → lower value = higher score (e.g. PE ratio)

    Example:
    normalize_0_to_1(33, 0, 200, inverse=True)
    → 1 - (33/200) = 0.835
    """
    if max_val == min_val:
        return 0.0

    score = (value - min_val) / (max_val - min_val)
    score = min(max(score, 0.0), 1.0)

    if inverse:
        score = 1.0 - score

    return round(score, 3)


def normalize_pe(pe_ratio: float) -> float:
    """PE ratio → 0-1. Lower PE = higher score."""
    if not pe_ratio or pe_ratio <= 0:
        return 0.0
    return normalize_0_to_1(pe_ratio, 0, 200, inverse=True)


def normalize_growth(revenue_growth: float) -> float:
    """Revenue growth → 0-1. Higher = better."""
    if revenue_growth is None:
        return 0.0
    return normalize_0_to_1(
        max(revenue_growth, 0.0), 0.0, 1.0
    )


def normalize_market_cap(market_cap: float) -> float:
    """Market cap → 0-1. Larger = more established."""
    if not market_cap or market_cap <= 0:
        return 0.0
    return normalize_0_to_1(market_cap, 0, 3e12)


def normalize_similarity(similarity: float) -> float:
    """Cosine similarity already 0-1. Just clamp."""
    if similarity is None:
        return 0.0
    return round(min(max(similarity, 0.0), 1.0), 3)


def normalize_sentiment(
    positive: int,
    negative: int
) -> float:
    """
    Sentiment score from keyword counts.
    0.0 = all negative
    0.5 = neutral
    1.0 = all positive
    """
    total = positive + negative
    if total == 0:
        return 0.5
    return round(positive / total, 3)


def apply_weights(scores: dict, weights: dict) -> float:
    """
    Apply weighted sum to dimension scores.

    scores  = {"valuation": 0.8, "growth": 0.7, ...}
    weights = {"valuation": 0.4, "growth": 0.3, ...}

    returns = (0.8×0.4) + (0.7×0.3) + ...
    """
    total = sum(
        scores.get(dim, 0.0) * weight
        for dim, weight in weights.items()
    )
    return round(total, 3)


def interpret_score(score: float) -> str:
    """Human readable interpretation of final score."""
    if score >= 0.80:
        return "Strong buy signal — high across all dimensions"
    elif score >= 0.65:
        return "Moderate buy signal — good fundamentals"
    elif score >= 0.50:
        return "Neutral — mixed signals"
    elif score >= 0.35:
        return "Caution — weak fundamentals"
    else:
        return "Avoid — poor signals across dimensions"


def build_score_breakdown(
    scores:      dict,
    weights:     dict,
    final_score: float
) -> dict:
    """
    Build explainability breakdown.
    Shows contribution of each dimension to final score.

    A score of None means the dimension had no evidence for this company and
    was excluded from the weighted sum. Its contribution is reported as None
    rather than 0.0, so the panel distinguishes "contributed nothing because
    it scored badly" from "was never measured".

    `effective_weights` are the weights actually applied — the raw weights
    renormalised over the measured dimensions — so the contributions sum to
    the final score instead of falling short of it.
    """
    measured = {
        dim: value
        for dim, value in scores.items()
        if value is not None
    }

    active_weight = sum(
        weights.get(dim, 0.0)
        for dim in measured
    )

    effective_weights = {
        dim: (
            round(weights.get(dim, 0.0) / active_weight, 3)
            if active_weight and dim in measured
            else 0.0
        )
        for dim in weights
    }

    contributions = {
        dim: (
            round(
                scores[dim] * weights.get(dim, 0.0) / active_weight,
                3,
            )
            if dim in measured and active_weight
            else None
        )
        for dim in weights
    }

    return {
        "final_score":   final_score,
        "interpretation": interpret_score(final_score),
        "scores":        scores,
        "weights":       weights,
        "effective_weights": effective_weights,
        "contributions": contributions,
        "unmeasured": [
            dim
            for dim in weights
            if dim not in measured
        ],
    }