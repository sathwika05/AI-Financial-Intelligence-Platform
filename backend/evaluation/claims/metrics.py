"""
Rates for the run, and agreement for the evaluator.

Both are computed from rows on read rather than stored on
evaluation_metrics. A stored aggregate drifts the moment a human relabels a
claim, and relabelling is the entire point of the validation page.

THE POSITIVE CLASS IS "UNSUPPORTED"
    Precision and recall describe how well the judge detects unsupported
    claims, not how often it is right overall. An accuracy figure over a
    mostly-supported corpus stays high while missing every fabrication,
    which is exactly the failure this evaluator exists to catch.

    So the number to read first is false_negatives: claims a human called
    unsupported that the judge waved through.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def claim_rates(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """
    How many claims the run made, and how many its evidence carried.

    unsupported_fact_rate divides by every claim, not by
    (supported + unsupported). Excluding the insufficient ones would let a
    run improve its headline number by retrieving less, which is the
    opposite of the incentive worth creating.
    """
    labels = [row.get("evaluator_label") for row in rows]
    total = len(labels)

    supported = labels.count("SUPPORTED")
    unsupported = labels.count("UNSUPPORTED")
    insufficient = labels.count("INSUFFICIENT_EVIDENCE")

    return {
        "total_claims": total,
        "supported": supported,
        "unsupported": unsupported,
        "insufficient_evidence": insufficient,
        "claim_support_rate": _rate(supported, total),
        "unsupported_fact_rate": _rate(unsupported, total),
    }


def agreement_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """
    How closely the judge matched a human, over the claims a human read.

    Rows without a human_label are ignored rather than counted as
    agreement -- an unlabelled claim is an unasked question, not a
    successful one.
    """
    validated = [
        row for row in rows
        if row.get("human_label")
    ]

    total = len(validated)

    if not total:
        return {
            "validated_claims": 0,
            "agreement": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "false_positives": 0,
            "false_negatives": 0,
        }

    matches = sum(
        1 for row in validated
        if row["evaluator_label"] == row["human_label"]
    )

    # INSUFFICIENT_EVIDENCE is not unsupported on either side: a retrieval
    # gap scored as a caught fabrication would flatter recall.
    true_positives = sum(
        1 for row in validated
        if row["evaluator_label"] == "UNSUPPORTED"
        and row["human_label"] == "UNSUPPORTED"
    )
    false_positives = sum(
        1 for row in validated
        if row["evaluator_label"] == "UNSUPPORTED"
        and row["human_label"] != "UNSUPPORTED"
    )
    false_negatives = sum(
        1 for row in validated
        if row["evaluator_label"] != "UNSUPPORTED"
        and row["human_label"] == "UNSUPPORTED"
    )

    precision = _rate(true_positives, true_positives + false_positives)
    recall = _rate(true_positives, true_positives + false_negatives)

    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0
    )

    return {
        "validated_claims": total,
        "agreement": _rate(matches, total),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }
