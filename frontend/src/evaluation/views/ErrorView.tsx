import type { RunMetrics } from "../api";
import {
  formatDateTime,
  formatPercent,
  formatScore,
  questionSetLabel,
  shortRunId,
} from "../format";
import { meanOf } from "../metrics";
import { Activity, ShieldAlert, TriangleAlert } from "lucide-react";
import { EmptyState, MetricRow, Panel } from "../components/primitives";

/**
 * What went wrong, at the granularity the API supports.
 *
 * Two distinct failure kinds are separated here: a run that never finished
 * (status `failed`, with the exception text the backend stored) and a run
 * that finished but produced weakly grounded answers (a high hallucination
 * rate or noise sensitivity). Per-question failures are not available.
 */
export function ErrorView({ runs }: { runs: RunMetrics[] }) {
  const failed = runs.filter((run) => run.status === "failed");
  const completed = runs.filter((run) => run.status === "completed");

  const worstGrounding = [...completed]
    .filter((run) => run.hallucination_rate != null)
    .sort(
      (a, b) => (b.hallucination_rate ?? 0) - (a.hallucination_rate ?? 0),
    )
    .slice(0, 8);

  if (runs.length === 0) {
    return (
      <EmptyState
        title="Nothing to analyse"
        detail="No benchmark runs have been recorded yet."
      />
    );
  }

  return (
    <div className="ev-grid">
      <Panel
        title="Failed Runs"
        note={`${failed.length} of ${runs.length}`}
        icon={TriangleAlert}
        tone="amber"
        span={12}
      >
        {failed.length === 0 ? (
          <p className="ev-note">
            No run has failed outright. Every recorded run reached a completed
            or in-progress state.
          </p>
        ) : (
          <div className="ev-tablewrap">
            <table className="ev-table">
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Started</th>
                  <th scope="col">Question Set</th>
                  <th scope="col">Provider</th>
                  <th scope="col">Error</th>
                </tr>
              </thead>

              <tbody>
                {failed.map((run) => (
                  <tr key={run.run_id}>
                    <td className="num">{shortRunId(run.run_id)}</td>
                    <td>{formatDateTime(run.created_at)}</td>
                    <td>
                      {questionSetLabel(run.question_set)}
                    </td>
                    <td>{run.provider_name ?? "—"}</td>
                    <td className="ev-table__error">
                      {run.error_message ?? "No message recorded"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Grounding Risk"
        note="Mean across completed runs"
        icon={ShieldAlert}
        tone="amber"
        span={4}
      >
        <MetricRow
          metricKey="hallucination_rate"
          current={meanOf(completed, "hallucination_rate")}
        />
        <MetricRow
          metricKey="noise_sensitivity"
          current={meanOf(completed, "noise_sensitivity")}
        />
        <MetricRow
          metricKey="faithfulness"
          current={meanOf(completed, "faithfulness")}
        />
        <MetricRow
          metricKey="context_precision"
          current={meanOf(completed, "context_precision")}
        />
      </Panel>

      <Panel
        title="Weakest Grounding by Run"
        note="Highest first"
        icon={Activity}
        tone="violet"
        span={8}
      >
        {worstGrounding.length === 0 ? (
          <p className="ev-note">
            No completed run has recorded a hallucination rate.
          </p>
        ) : (
          <div className="ev-tablewrap">
            <table className="ev-table">
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Question Set</th>
                  <th scope="col" className="ev-table__num">
                    Hallucination
                  </th>
                  <th scope="col" className="ev-table__num">
                    Faithfulness
                  </th>
                  <th scope="col" className="ev-table__num">
                    Pass Rate
                  </th>
                </tr>
              </thead>

              <tbody>
                {worstGrounding.map((run) => (
                  <tr key={run.run_id}>
                    <td className="num">{shortRunId(run.run_id)}</td>
                    <td>
                      {questionSetLabel(run.question_set)}
                    </td>
                    <td className="ev-table__num num">
                      {formatPercent(run.hallucination_rate)}
                    </td>
                    <td className="ev-table__num num">
                      {formatScore(run.faithfulness)}
                    </td>
                    <td className="ev-table__num num">
                      {formatPercent(run.pass_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
