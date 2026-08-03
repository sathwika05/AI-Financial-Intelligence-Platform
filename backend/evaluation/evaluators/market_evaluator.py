from typing import Any

from backend.evaluation.schemas import EvaluatorResult


class MarketEvaluator:
    name = "market"

    def evaluate(
        self,
        *,
        market_result: Any,
        expected_companies: list[str],
    ) -> EvaluatorResult:
        if market_result is None:
            return EvaluatorResult(
                evaluator=self.name,
                applicable=True,
                passed=False,
                metrics={
                    "market_execution_success": 0.0,
                    "market_company_coverage": 0.0,
                },
                errors=["Market result is missing."],
            )

        if isinstance(market_result, dict):
            error = market_result.get("error")

            if error:
                return EvaluatorResult(
                    evaluator=self.name,
                    applicable=True,
                    passed=False,
                    metrics={
                        "market_execution_success": 0.0,
                        "market_company_coverage": 0.0,
                    },
                    errors=[str(error)],
                )

        available_tickers = self._extract_tickers(
            market_result
        )

        expected = {
            ticker.upper()
            for ticker in expected_companies
        }

        if expected:
            coverage = len(
                available_tickers & expected
            ) / len(expected)
        else:
            coverage = float(bool(available_tickers))

        return EvaluatorResult(
            evaluator=self.name,
            applicable=True,
            passed=coverage >= 0.8,
            metrics={
                "market_execution_success": 1.0,
                "market_company_coverage": round(
                    coverage,
                    4,
                ),
            },
        )

    @staticmethod
    def _extract_tickers(
        market_result: Any,
    ) -> set[str]:
        tickers: set[str] = set()

        if isinstance(market_result, dict):
            data = market_result.get(
                "data",
                market_result,
            )

            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, dict):
                        ticker = (
                            value.get("ticker")
                            or value.get("symbol")
                            or key
                        )
                        tickers.add(str(ticker).upper())

            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        ticker = (
                            item.get("ticker")
                            or item.get("symbol")
                        )

                        if ticker:
                            tickers.add(str(ticker).upper())

        return tickers