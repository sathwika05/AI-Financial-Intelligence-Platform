"""
Finance-specific market-data evaluator.

Purpose
-------
Evaluate ticker coverage, field completeness, degraded-mode handling,
and optional comparison with golden market values.

Golden dataset inputs
---------------------
expected_companies
expected_market_data

Pipeline output
---------------
market_result

Metric produced
---------------
market_accuracy


"""
from __future__ import annotations

from numbers import Number
from typing import Any

from backend.evaluation.schemas import EvaluatorResult
from backend.observability.logging import log_span


class MarketEvaluator:
    """Evaluate market-data coverage, completeness, and optional value accuracy."""

    REQUIRED_FIELDS = {
        "current_price",
        "market_cap",
        "pe_ratio",
        "volume",
    }

    def __init__(
        self,
        *,
        numeric_tolerance: float = 0.05,
    ) -> None:
        """
        numeric_tolerance:
            Relative tolerance for time-sensitive golden market values.
            0.05 means ±5%.
        """
        self.numeric_tolerance = numeric_tolerance

    @log_span("expected_companies")
    def evaluate(
        self,
        *,
        market_result: Any,
        expected_companies: list[str],
        expected_market_data: dict[
            str,
            dict[str, Any],
        ] | None = None,
    ) -> EvaluatorResult:
        expected_tickers = {
            value.strip().upper()
            for value in expected_companies
            if value
        }

        expected_market_data = (
            expected_market_data
            or {}
        )

        actual_data = self._extract_data(
            market_result
        )

        normalized_actual = {
            str(ticker).strip().upper(): value
            for ticker, value in actual_data.items()
            if isinstance(
                value,
                dict,
            )
        }

        actual_tickers = set(
            normalized_actual.keys()
        )

        ticker_coverage = (
            len(
                expected_tickers
                & actual_tickers
            )
            / len(expected_tickers)
            if expected_tickers
            else (
                1.0
                if actual_tickers
                else 0.0
            )
        )

        completeness_values = [
            self._completeness(record)
            for record in normalized_actual.values()
        ]

        data_completeness = (
            sum(completeness_values)
            / len(completeness_values)
            if completeness_values
            else 0.0
        )

        value_accuracy = self._golden_value_accuracy(
            actual_data=normalized_actual,
            expected_market_data=expected_market_data,
        )

        degraded = (
            bool(
                market_result.get(
                    "degraded"
                )
            )
            if isinstance(
                market_result,
                dict,
            )
            else False
        )

        components = [
            (ticker_coverage, 0.60),
            (data_completeness, 0.20),
        ]

        # Use exact golden-value validation when expected_market_data is available.
        if value_accuracy is not None:
            components.append(
                (
                    value_accuracy,
                    0.20,
                )
            )
        else:
            # Redistribute the unused score weight to ticker coverage when no golden values exist.
            components[0] = (
                ticker_coverage,
                0.80,
            )

        market_accuracy = sum(
            value * weight
            for value, weight in components
        )

        if degraded:
            market_accuracy *= 0.75

        market_accuracy = self._clamp(
            market_accuracy
        )

        details = {
            "expected_companies": sorted(
                expected_tickers
            ),
            "returned_tickers": sorted(
                actual_tickers
            ),
            "ticker_coverage": round(
                ticker_coverage,
                4,
            ),
            "data_completeness": round(
                data_completeness,
                4,
            ),
            "value_accuracy": (
                round(
                    value_accuracy,
                    4,
                )
                if value_accuracy is not None
                else None
            ),
            "degraded": degraded,
            "numeric_tolerance": self.numeric_tolerance,
        }

        return EvaluatorResult(
            evaluator="market",
            applicable=True,
            passed=(
                bool(normalized_actual)
                and market_accuracy >= 0.70
            ),
            score=round(
                market_accuracy,
                4,
            ),
            metrics={
                "market_accuracy": round(
                    market_accuracy,
                    4,
                ),
            },
            details=details,
            errors=(
                []
                if normalized_actual
                else ["No market data was returned."]
            ),
        )

    @staticmethod
    def _extract_data(
        market_result: Any,
    ) -> dict[str, Any]:
        if not isinstance(
            market_result,
            dict,
        ):
            return {}

        nested = market_result.get(
            "market_data"
        )

        if isinstance(
            nested,
            dict,
        ):
            return nested

        return {
            key: value
            for key, value in market_result.items()
            if isinstance(
                value,
                dict,
            )
        }

    @classmethod
    def _completeness(
        cls,
        record: dict[str, Any],
    ) -> float:
        populated = sum(
            1
            for field in cls.REQUIRED_FIELDS
            if record.get(field) is not None
        )

        return (
            populated
            / len(cls.REQUIRED_FIELDS)
        )

    def _golden_value_accuracy(
        self,
        *,
        actual_data: dict[
            str,
            dict[str, Any],
        ],
        expected_market_data: dict[
            str,
            dict[str, Any],
        ],
    ) -> float | None:
        if not expected_market_data:
            return None

        comparisons: list[float] = []

        for ticker, expected_fields in (
            expected_market_data.items()
        ):
            normalized_ticker = (
                ticker.strip().upper()
            )

            actual_fields = actual_data.get(
                normalized_ticker
            )

            if actual_fields is None:
                comparisons.append(
                    0.0
                )
                continue

            for field, expected_value in (
                expected_fields.items()
            ):
                actual_value = actual_fields.get(
                    field
                )

                comparisons.append(
                    self._value_match(
                        actual_value=actual_value,
                        expected_value=expected_value,
                    )
                )

        return (
            sum(comparisons)
            / len(comparisons)
            if comparisons
            else None
        )

    def _value_match(
        self,
        *,
        actual_value: Any,
        expected_value: Any,
    ) -> float:
        if actual_value is None:
            return 0.0

        if (
            isinstance(actual_value, Number)
            and isinstance(expected_value, Number)
        ):
            if expected_value == 0:
                return (
                    1.0
                    if actual_value == 0
                    else 0.0
                )

            relative_error = abs(
                (
                    float(actual_value)
                    - float(expected_value)
                )
                / float(expected_value)
            )

            return (
                1.0
                if relative_error
                <= self.numeric_tolerance
                else 0.0
            )

        return (
            1.0
            if str(actual_value).strip().lower()
            == str(expected_value).strip().lower()
            else 0.0
        )

    @staticmethod
    def _clamp(
        value: float,
    ) -> float:
        return max(
            0.0,
            min(
                1.0,
                value,
            ),
        )
