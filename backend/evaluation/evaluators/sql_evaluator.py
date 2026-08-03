






from typing import Any

from backend.evaluation.schemas import EvaluatorResult


class SQLEvaluator:
    name = "sql"

    def evaluate(
            self,
            *,
            generated_sql: str | None,
            actual_result: Any,
            expected_result: Any | None = None,
            expected_sql: str | None = None,
            ) -> EvaluatorResult:
          if not generated_sql:
               return EvaluatorResult(
                    evaluator=self.name,
                    applicable=True,
                    passed=False,
                    metrics={
                         "sql_generated": 0.0,
                         "sql_execution_success": 0.0,
                    },
                    errors = ["No SQL query was generated."],
               )

          execution_success = float(
               self._is_successful_result(actual_result)
          )

          metrics: dict[str, float] = {
               "sql_generated": 1.0,
               "sql_execution_success": execution_success
          }

          if expected_result is not None:
               result_match = float(
                    self._normalize(actual_result)
                    == self._normalize(expected_result)
               )
               metrics["sql_result_exact_match"] = result_match

          if expected_sql:
               sql_exact_match = float(
                    self._normalize_sql(generated_sql)
                    == self._normalize_sql(expected_sql)
               )
               metrics["sql_exact_match"]= sql_exact_match

          passed = execution_success == 1.0

          if "sql_result_exact_match" in metrics:
               passed = (
                    passed
                    and metrics["sql_result_exact_match"] == 1.0
               )
          return EvaluatorResult(
               evaluator=self.name,
               applicable= True,
               passed = passed,
               metrics= metrics,
          )

    @staticmethod
    def _is_successful_result(result: Any) -> bool:
         if result is None:
              return False

         if isinstance(result, dict):
              if result.get("error"):
                   return False

              if "answer" in result:
                   return result["answer"] is not None
         return True

    @staticmethod
    def _normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: SQLEvaluator._normalize(item)
                for key, item in sorted(value.items())
                if key not in {"latency_ms", "cached"}
            }

        if isinstance(value, list):
            normalized = [
                SQLEvaluator._normalize(item)
                for item in value
            ]

            try:
                return sorted(
                    normalized,
                    key=lambda item: str(item),
                )
            except TypeError:
                return normalized

        return value

    @staticmethod
    def _normalize_sql(sql: str) -> str:
        return " ".join(
            sql.strip().lower().rstrip(";").split()
        )

             
         

          
          
               
          

