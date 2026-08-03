




from backend.evaluation.schemas import EvaluatorResult


class IntentEvaluator:
    name = "intent"

    def evaluate(
            self,
            *,
            expected_intent: str,
            actual_intent: str | None,
    ) -> EvaluatorResult:
        expected = expected_intent.strip().upper()
        actual = (actual_intent or "").strip().upper()

        accuracy = float(expected == actual)

        return EvaluatorResult(
            evaluator=self.name,
            applicable= True,
            passed=bool(accuracy),
            metrics = {
                "intent_accuracy": accuracy,
            },
        )
        