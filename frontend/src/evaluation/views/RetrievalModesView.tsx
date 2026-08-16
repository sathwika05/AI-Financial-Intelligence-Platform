import { Search } from "lucide-react";
import { RETRIEVAL_MODES, type RunMetrics } from "../api";
import { formatDateTime, formatPercent, retrievalLabel } from "../format";
import { groupRuns, meanOf } from "../metrics";
import { EmptyState, Panel } from "../components/primitives";

/**
 * The retrieval strategies the pipeline can run, and how each has performed.
 *
 * A catalogue rather than a comparison: it lists every mode the benchmark
 * accepts — including ones never exercised — so an unused strategy is
 * visible. Retrieval Comparison covers the metric-by-metric view.
 */

/** What each mode does, from the graph's retrieval layer. */
const MODE_DESCRIPTION: Record<string, string> = {
  "hybrid+reranker":
    "BM25 and vector search fused with RRF, then re-scored by the reranker before the top K is kept.",
  hybrid:
    "BM25 and vector search fused with reciprocal rank fusion, without a reranking pass.",
  vector: "Dense vector similarity over document chunks only.",
  sql: "Structured queries against the financial metrics tables only.",
};

export function RetrievalModesView({ runs }: { runs: RunMetrics[] }) {
  const groups = groupRuns(runs, "retrieval_mode");

  const usage = new Map(groups.map((group) => [group.label, group.runs]));

  // Every configurable mode, plus any historical mode no longer offered.
  const modes = [
    ...RETRIEVAL_MODES,
    ...groups
      .map((group) => group.label)
      .filter(
        (label) => !RETRIEVAL_MODES.includes(label as never),
      ),
  ];

  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs recorded"
        detail="Modes are listed with their measured performance once at least one benchmark has completed."
      />
    );
  }

  return (
    <div className="ev-grid">
      <Panel
        title="Retrieval Modes"
        note={`${modes.length} configurable`}
        icon={Search}
        tone="blue"
        span={12}
      >
        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">Mode</th>
                <th scope="col">What it does</th>
                <th scope="col" className="ev-table__num">
                  Completed runs
                </th>
                <th scope="col" className="ev-table__num">
                  Mean pass rate
                </th>
                <th scope="col" className="ev-table__num">
                  Mean faithfulness
                </th>
                <th scope="col">Last used</th>
              </tr>
            </thead>

            <tbody>
              {modes.map((mode) => {
                const modeRuns = usage.get(mode) ?? [];

                // groupRuns returns newest-first within each group.
                const lastUsed = modeRuns[0]?.created_at;

                return (
                  <tr key={mode}>
                    <td>{retrievalLabel(mode)}</td>
                    <td className="ev-table__muted">
                      {MODE_DESCRIPTION[mode] ?? "—"}
                    </td>
                    <td className="ev-table__num">{modeRuns.length}</td>
                    <td className="ev-table__num">
                      {modeRuns.length === 0
                        ? "—"
                        : formatPercent(meanOf(modeRuns, "pass_rate"))}
                    </td>
                    <td className="ev-table__num">
                      {modeRuns.length === 0
                        ? "—"
                        : (meanOf(modeRuns, "faithfulness")?.toFixed(2) ?? "—")}
                    </td>
                    <td className="ev-table__muted">
                      {lastUsed ? formatDateTime(lastUsed) : "never run"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
