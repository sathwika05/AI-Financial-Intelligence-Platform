






from backend.evaluation.schemas import EvaluatorResult


class ToolEvaluator:
    name = "tool"

    def evaluate(
            self,
            *,
            expected_tools: list[str],
            executed_tools: list[str],
    ) -> EvaluatorResult:
        expected = {
            self._normalize_tool(tool)
            for tool in expected_tools
        }

        executed = {
            self._normalize_tool(tool)
            for tool in executed_tools
        }

        if not expected:
            return EvaluatorResult(
                evaluator=self.name,
                applicable= False,
                passed=None,
                metrics={},
            )

        true_positive = len(expected & executed)
        false_positive = len(executed - expected)
        false_negative = len(expected-executed)

        precision_denominator = true_positive + false_positive
        recall_denominator = true_positive +false_negative

        precision = (
            true_positive / precision_denominator
            if precision_denominator
            else 0.0
        )     

        recall = (
            true_positive / recall_denominator
            if recall_denominator
            else 0.0
        )   

        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )

        exact_match = float(expected == executed)

        return EvaluatorResult(
            evaluator = self.name,
            applicable = True,
            passed = expected == executed,
            metrics ={
                "tool_precision": round(precision, 4),
                "tool_recall": round(recall, 4),
                "tool_f1": round(f1, 4),
                "tool_excat_match": exact_match
            },
        )

@staticmethod
def _normalize_tool(tool: str) -> str:
    normalized = tool.strip().lower()

    alias = {
        "sql_query": "sql",
        "sql_tool": "sql",
        "vector_query": "vector",
        "vector_search": "vector",
        "retrieval": "vector",
        "market_query": "market",
        "market_api": "market",
    }

    return alias.get(normalized, normalized)