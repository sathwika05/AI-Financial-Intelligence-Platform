import { useState } from "react";
import type { RunMetrics } from "../api";
import { formatCost, formatDate, formatLatency } from "../format";
import { getSpec, type MetricKey } from "../metrics";
import { LineChart } from "../components/charts";
import { Activity, CircleDollarSign, Gauge } from "lucide-react";
import { EmptyState, Panel } from "../components/primitives";
import { SERIES, colorAt } from "../palette";

/**
 * Metrics over the run history.
 *
 * The x axis is the sequence of completed runs, not calendar time — runs are
 * irregular, and stretching them onto a date scale would imply a sampling
 * rate the data does not have.
 */

const QUALITY_KEYS: MetricKey[] = [
  "pass_rate",
  "route_accuracy",
  "faithfulness",
  "response_relevancy",
  "context_precision",
  "context_recall",
  "hallucination_rate",
  "ndcg_at_k",
  "mrr",
];

const DEFAULT_SELECTION: MetricKey[] = [
  "pass_rate",
  "faithfulness",
  "context_precision",
];

export function TrendView({ runs }: { runs: RunMetrics[] }) {
  const [selected, setSelected] = useState<MetricKey[]>(DEFAULT_SELECTION);

  const history = runs
    .filter((run) => run.status === "completed")
    .slice()
    .reverse();

  if (history.length < 2) {
    return (
      <EmptyState
        title="Not enough history"
        detail="At least two completed runs are needed before a trend means anything."
      />
    );
  }

  const categories = history.map((run) => formatDate(run.created_at));

  const toggle = (key: MetricKey) =>
    setSelected((current) =>
      current.includes(key)
        ? current.filter((entry) => entry !== key)
        : [...current, key],
    );

  return (
    <div className="ev-grid">
      <Panel
        title="Quality Trend"
        note={`${history.length} completed runs`}
        icon={Activity}
        tone="violet"
        span={12}
      >
        <div className="ev-toggles">
          {QUALITY_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className={`ev-toggle${
                selected.includes(key) ? " ev-toggle--on" : ""
              }`}
              onClick={() => toggle(key)}
              aria-pressed={selected.includes(key)}
            >
              {getSpec(key).label}
            </button>
          ))}
        </div>

        {selected.length === 0 ? (
          <p className="ev-note">Select at least one metric to plot.</p>
        ) : (
          <LineChart
            categories={categories}
            series={selected.map((key, index) => ({
              label: getSpec(key).label,
              color: colorAt(index),
              values: history.map((run) => {
                const value = run[key];

                return typeof value === "number" ? value : null;
              }),
            }))}
            formatValue={(value) => value.toFixed(2)}
            height={280}
            // See SummaryView: a fitted baseline is what makes a change of a
            // few hundredths visible at all.
            zeroBased={false}
          />
        )}
      </Panel>

      <Panel
        title="Cost Trend"
        note="USD"
        icon={CircleDollarSign}
        tone="amber"
        span={6}
      >
        <LineChart
          categories={categories}
          series={[
            {
              label: "Total cost per run",
              color: SERIES.amber,
              values: history.map((run) => run.total_cost),
            },
            {
              label: "Cost per question",
              color: SERIES.rose,
              values: history.map((run) => run.cost_per_request),
            },
          ]}
          formatValue={(value) => formatCost(value)}
        />
      </Panel>

      <Panel
        title="Latency Trend"
        note="Per question"
        icon={Gauge}
        tone="blue"
        span={6}
      >
        <LineChart
          categories={categories}
          series={[
            {
              label: "Average",
              color: SERIES.indigo,
              values: history.map((run) => run.avg_latency_ms),
            },
            {
              label: "P95",
              color: SERIES.violet,
              values: history.map((run) => run.p95_latency),
            },
            {
              label: "P99",
              color: SERIES.sky,
              values: history.map((run) => run.p99_latency),
            },
          ]}
          formatValue={(value) => formatLatency(value)}
          zeroBased={false}
        />
      </Panel>
    </div>
  );
}
