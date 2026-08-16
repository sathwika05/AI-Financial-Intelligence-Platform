import { Target } from "lucide-react";
import type { RunMetrics } from "../api";
import { formatPercent, shortRunId } from "../format";
import { Panel } from "../components/primitives";

/**
 * The one screen in the design reference with nothing behind it.
 *
 * `BenchmarkRunner` builds a `QuestionEvaluationResult` per question —
 * question text, expected and actual route, evaluator scores, pass/fail,
 * latency and cost — but only the run-level aggregate is persisted, so there
 * is nothing to read back. Rather than invent rows, this states what exists,
 * what is missing, and what would make it work.
 */
export function PerQuestionView({ run }: { run: RunMetrics | null }) {
  return (
    <div className="ev-grid">
      <Panel
        title="Per-Question Results"
        note="Not persisted"
        icon={Target}
        tone="amber"
        span={12}
      >
        <p className="ev-note">
          The benchmark runner evaluates every question individually and keeps
          the result in memory — question text, expected and actual route,
          each evaluator's score, pass/fail, latency and cost. Only the
          run-level average survives: <code>evaluation_metrics</code> stores
          one row per run, and <code>question_results</code> is discarded when
          the run finishes.
        </p>

        <p className="ev-note" style={{ marginTop: 10 }}>
          Making this table real needs a table keyed on{" "}
          <code>run_id</code> + <code>question_id</code>, a write in the
          runner, and an endpoint to read it back. Until then the only
          per-question detail available is what LangSmith captured for the
          traced run.
        </p>

        {run && (
          <p className="ev-note" style={{ marginTop: 10 }}>
            For {shortRunId(run.run_id)} the aggregate says{" "}
            {run.total_requests} questions ran at a{" "}
            {formatPercent(run.pass_rate)} pass rate — roughly{" "}
            {run.pass_rate == null
              ? "an unknown number"
              : Math.round(run.pass_rate * run.total_requests)}{" "}
            passed — but which ones is not recorded.
          </p>
        )}
      </Panel>
    </div>
  );
}
