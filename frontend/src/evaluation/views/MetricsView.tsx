import type { RunMetrics } from "../api";
import {
  questionSetLabel,
} from "../format";
import {
  PANELS,
  formatMetric,
  getSpec,
  readMetric,
  type MetricKey,
} from "../metrics";
import { BarChart3, Sparkles } from "lucide-react";
import { RankedBars } from "../components/charts";
import {
  DeltaBadge,
  EmptyState,
  Panel,
  ScoreBar,
} from "../components/primitives";
import { SERIES } from "../palette";

/**
 * The full metric catalog for one run, grouped by evaluator.
 *
 * Where the summary shows the headline figures, this view shows every field
 * the endpoints return, including the ones with no value — an unmeasured
 * evaluator is itself worth seeing.
 */

/** The 0–1 metrics that read usefully as a ranked bar list. */
const SCORE_KEYS: MetricKey[] = [
  "faithfulness",
  "response_relevancy",
  "context_precision",
  "context_recall",
  "context_entity_recall",
  "precision_at_k",
  "recall_at_k",
  "ndcg_at_k",
  "mrr",
  "sql_accuracy",
  "sql_equivalence",
  "tool_accuracy",
  "tool_f1",
  "market_accuracy",
  "intent_accuracy",
];

export function MetricsView({
  run,
  previous,
}: {
  run: RunMetrics | null;
  previous: RunMetrics | null;
}) {
  if (!run) {
    return (
      <EmptyState
        title="Select a run"
        detail="Pick a run from the Runs screen to see its complete metric breakdown."
      />
    );
  }

  const scoreBars = SCORE_KEYS.map((key) => ({
    label: getSpec(key).label,
    value: readMetric(run, key),
    color: SERIES.indigo,
  })).filter((bar) => bar.value != null);

  return (
    <div className="ev-grid">
      <Panel
        title="All Metrics"
        note={`${questionSetLabel(run.question_set)} · k=${run.k ?? "—"}`}
        icon={Sparkles}
        tone="violet"
        span={12}
      >
        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Group</th>
                <th scope="col">Better</th>
                <th scope="col" className="ev-table__num">
                  Value
                </th>
                <th scope="col">Scale</th>
                <th scope="col" className="ev-table__num">
                  vs prev
                </th>
              </tr>
            </thead>

            <tbody>
              {PANELS.flatMap((panel) =>
                panel.keys.map((key) => {
                  const spec = getSpec(key);
                  const current = readMetric(run, key);

                  return (
                    <tr key={`${panel.id}-${key}`}>
                      <td title={spec.hint}>{spec.label}</td>
                      <td className="ev-table__muted">{panel.title}</td>
                      <td className="ev-table__muted">
                        {spec.direction === "neutral"
                          ? "—"
                          : spec.direction === "higher"
                            ? "higher"
                            : "lower"}
                      </td>
                      <td className="ev-table__num num">
                        {formatMetric(key, current)}
                      </td>
                      <td>
                        {spec.kind === "score" || spec.kind === "rate" ? (
                          <ScoreBar value={current} />
                        ) : (
                          <span className="ev-table__muted">—</span>
                        )}
                      </td>
                      <td className="ev-table__num">
                        <DeltaBadge
                          metricKey={key}
                          current={current}
                          previous={readMetric(previous, key)}
                        />
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      {scoreBars.length > 0 && (
        <Panel
          title="Scores at a Glance"
          note="0 – 1"
          icon={BarChart3}
          tone="blue"
          span={12}
        >
          <RankedBars
            bars={[...scoreBars].sort(
              (a, b) => (b.value ?? 0) - (a.value ?? 0),
            )}
            formatValue={(value) => value.toFixed(2)}
            max={1}
          />
        </Panel>
      )}
    </div>
  );
}
