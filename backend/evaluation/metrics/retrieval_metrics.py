







from collections.abc import Sequence
import math


def precision_at_k(
        retrieved: Sequence[str],
        relevant: Sequence[str],
        k:int,
) -> float:
    if k<=0:
        raise ValueError("k must be greater than zero")

    top_k = list(retrieved[:k])
    relevant_set = set(relevant)

    if not top_k:
        return 0.0

    relevant_retrieved = sum(
        item in relevant_set
        for item in top_k
    )

    return relevant_retrieved / len(top_k)

def recall_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be greater than zero")

    relevant_set = set(relevant)

    if not relevant_set:
        return 0.0

    top_k = set(retrieved[:k])

    return len(top_k & relevant_set) / len(relevant_set)

def reciprocal_rank(
    retrieved: Sequence[str],
    relevant: Sequence[str],
) -> float:
    relevant_set = set(relevant)

    for index, item in enumerate(retrieved, start=1):
        if item in relevant_set:
            return 1.0 / index

    return 0.0

def hit_rate_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str],
    k: int,
) -> float:
    relevant_set = set(relevant)
    top_k = set(retrieved[:k])

    return float(bool(top_k & relevant_set))


def ndcg_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str],
    k: int,
) -> float:
    relevant_set = set(relevant)
    top_k = list(retrieved[:k])

    dcg = 0.0

    for index, item in enumerate(top_k, start=1):
        relevance = 1.0 if item in relevant_set else 0.0
        dcg += relevance / math.log2(index + 1)

    ideal_hits = min(len(relevant_set), k)

    if ideal_hits == 0:
        return 0.0

    ideal_dcg = sum(
        1.0 / math.log2(index + 1)
        for index in range(1, ideal_hits + 1)
    )

    return dcg / ideal_dcg if ideal_dcg else 0.0
    