import type { RunMetrics } from "../api";
import {
  formatCost,
  formatDateTime,
  formatDuration,
  formatLatency,
  formatPercent,
  formatScore,
  questionSetLabel,
  retrievalLabel,
  shortRunId,
} from "../format";
import { Layers3 } from "lucide-react";
import { EmptyState, Panel, StatusPill } from "../components/primitives";

/** Every run the API returns, newest first, with the figures worth scanning. */
export function RunsView({
  runs,
  selectedRunId,
  onSelect,
}: {
  runs: RunMetrics[];
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
}) {
  if (runs.length === 0) {
    return (
      <EmptyState
        title="No benchmark runs recorded"
        detail="Runs appear here the moment one is queued, and update as it progresses."
      />
    );
  }

  return (
    <Panel
      title="Benchmark Runs"
      note={`${runs.length} recorded`}
      icon={Layers3}
      tone="violet"
      span={12}
    >
      <div className="ev-tablewrap">
        <table className="ev-table">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Status</th>
              <th scope="col">Started</th>
              <th scope="col">Duration</th>
              <th scope="col">Provider</th>
              <th scope="col">Retrieval</th>
              <th scope="col">Question Set</th>
              <th scope="col" className="ev-table__num">
                Questions
              </th>
              <th scope="col" className="ev-table__num">
                Pass Rate
              </th>
              <th scope="col" className="ev-table__num">
                Route Acc.
              </th>
              <th scope="col" className="ev-table__num">
                Faithful.
              </th>
              <th scope="col" className="ev-table__num">
                Avg Latency
              </th>
              <th scope="col" className="ev-table__num">
                Cost
              </th>
            </tr>
          </thead>

          <tbody>
            {runs.map((run) => (
              <tr
                key={run.run_id}
                className={
                  run.run_id === selectedRunId ? "ev-table__row--active" : ""
                }
                onClick={() => onSelect(run.run_id)}
                // Rows act as buttons: selecting one drives every other view.
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(run.run_id);
                  }
                }}
              >
                <td className="num">{shortRunId(run.run_id)}</td>
                <td>
                  <StatusPill status={run.status} />
                </td>
                <td>{formatDateTime(run.created_at)}</td>
                <td className="num">
                  {formatDuration(run.created_at, run.completed_at)}
                </td>
                <td>{run.provider_name ?? "—"}</td>
                <td>{retrievalLabel(run.retrieval_mode)}</td>
                <td>{questionSetLabel(run.question_set)}</td>
                <td className="ev-table__num num">{run.total_requests}</td>
                <td className="ev-table__num num">
                  {formatPercent(run.pass_rate)}
                </td>
                <td className="ev-table__num num">
                  {formatPercent(run.route_accuracy)}
                </td>
                <td className="ev-table__num num">
                  {formatScore(run.faithfulness)}
                </td>
                <td className="ev-table__num num">
                  {formatLatency(run.avg_latency_ms)}
                </td>
                <td className="ev-table__num num">
                  {formatCost(run.total_cost)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
