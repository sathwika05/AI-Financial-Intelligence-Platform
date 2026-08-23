import { Target } from "lucide-react";
import type { RunMetrics } from "../api";
import { formatScore, shortRunId } from "../format";
import { useRunQuestions } from "../useEvaluationData";
import {
  EmptyState,
  Panel,
  ScoreBar,
  StatusPill,
} from "../components/primitives";

/**
 * Per-question detail, read back from `question_results`.
 *
 * This screen used to explain why it was empty: the runner built a result
 * per question and only the run-level aggregate was persisted. That is no
 * longer true — results are written per question as the run goes, so a run
 * that dies keeps what it already scored.
 */
/** The panel on its own, for embedding in a grid a caller already owns. */
export function PerQuestionPanel({ run }: { run: RunMetrics | null }) {
  const {
    questions: rows,
    status,
    error,
  } = useRunQuestions(run?.run_id ?? null);

  const loading = status === "idle" || status === "loading";
  const failed = rows.filter((row) => row.passed === false).length;

  return (
    <Panel
      title="Per-Question Results"
      note={
        rows.length ? `${rows.length} questions · ${failed} failed` : undefined
      }
      icon={Target}
      span={12}
    >
      {!run && (
        <EmptyState
          title="No run selected"
          detail="Pick a run to see how each of its questions scored."
        />
      )}

      {run && error && (
        <EmptyState title="Could not load results" detail={error} />
      )}

      {run && !error && !rows.length && (
        <EmptyState
          title={loading ? "Loading…" : "No questions recorded"}
          detail={
            loading
              ? `Reading the results for ${shortRunId(run.run_id)}.`
              : `Run ${shortRunId(run.run_id)} has no stored questions. Runs from before per-question results were persisted show nothing here.`
          }
        />
      )}

      {rows.length > 0 && (
        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col">Route</th>
                <th scope="col" className="ev-table__num">
                  Score
                </th>
                <th scope="col">Result</th>
              </tr>
            </thead>

            <tbody>
              {rows.map((row) => {
                // A route the planner got wrong is worth seeing next to the
                // score it produced, since a misroute takes the tool
                // evaluator down with it.
                const misrouted =
                  row.expected_intent != null &&
                  row.actual_intent != null &&
                  row.expected_intent !== row.actual_intent;

                return (
                  <tr key={row.question_id}>
                    <td>
                      <div className="ev-mono">{row.question_id}</div>
                      <div className="ev-note">{row.question}</div>
                    </td>

                    <td>
                      {misrouted ? (
                        <>
                          {row.actual_intent}{" "}
                          <span className="ev-note">
                            (expected {row.expected_intent})
                          </span>
                        </>
                      ) : (
                        (row.actual_intent ?? "—")
                      )}
                    </td>

                    <td className="ev-table__num">
                      {formatScore(row.overall_score)}
                      <ScoreBar value={row.overall_score} />
                    </td>

                    <td>
                      <StatusPill
                        status={row.passed ? "completed" : "failed"}
                      />
                      {row.error && <div className="ev-note">{row.error}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/** The full-screen view, which owns its own grid. */
export function PerQuestionView({ run }: { run: RunMetrics | null }) {
  return (
    <div className="ev-grid">
      <PerQuestionPanel run={run} />
    </div>
  );
}
