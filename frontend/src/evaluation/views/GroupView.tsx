import type { RunMetrics } from "../api";
import { parseModelSnapshot, retrievalLabel, titleCase } from "../format";
import {
  formatMetric,
  getSpec,
  groupRuns,
  meanOf,
  type MetricKey,
} from "../metrics";
import { RankedBars } from "../components/charts";
import { BarChart3, Search, Target } from "lucide-react";
import { EmptyState, Panel } from "../components/primitives";
import { colorAt } from "../palette";

/**
 * Cross-run comparison by configuration.
 *
 * No endpoint aggregates across runs, but every run carries the configuration
 * it executed under, so grouping the run history by retrieval mode or by
 * model snapshot and averaging gives a real — if small-sample — comparison.
 * The run count per group is always shown, because a mean over one run is a
 * very different claim from a mean over twenty.
 */

export type GroupField =
  | "retrieval_mode"
  | "model"
  | "question_set"
  | "dataset";

const COLUMN_LABEL: Record<GroupField, string> = {
  retrieval_mode: "Retrieval mode",
  model: "Model snapshot",
  question_set: "Question set",
  dataset: "Dataset",
};

const COMPARED_KEYS: MetricKey[] = [
  "pass_rate",
  "route_accuracy",
  "faithfulness",
  "context_precision",
  "context_recall",
  "ndcg_at_k",
  "hallucination_rate",
  "avg_latency_ms",
  "cost_per_request",
];

/**
 * Group labels for display. A model snapshot is stored as
 * "small=x, medium=y, large=z", which is too wide for a bar label, so the
 * tier keys are dropped and only the model names kept.
 */
function groupLabel(field: GroupField, label: string): string {
  if (field === "retrieval_mode") {
    return retrievalLabel(label);
  }

  if (field === "question_set") {
    return titleCase(label);
  }

  // Datasets are already stored as display names ("SEC Filings").
  if (field === "dataset") {
    return label;
  }

  const tiers = parseModelSnapshot(label);

  return tiers.length > 0
    ? tiers.map((tier) => tier.model).join(" / ")
    : label;
}

export function GroupView({
  runs,
  field,
  title,
  emptyDetail,
}: {
  runs: RunMetrics[];
  field: GroupField;
  title: string;
  emptyDetail: string;
}) {
  const groups = groupRuns(runs, field);

  if (groups.length === 0) {
    return <EmptyState title="Nothing to compare yet" detail={emptyDetail} />;
  }

  return (
    <div className="ev-grid">
      <Panel
        title={title}
        note={`${groups.length} group${groups.length === 1 ? "" : "s"}`}
        icon={field === "model" ? BarChart3 : Search}
        tone="blue"
        span={12}
      >
        {groups.length === 1 && (
          <p className="ev-note">
            Only one {COLUMN_LABEL[field].toLowerCase()} has completed runs, so
            there is nothing to compare it against yet.
          </p>
        )}

        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">{COLUMN_LABEL[field]}</th>
                <th scope="col" className="ev-table__num">
                  Runs
                </th>
                {COMPARED_KEYS.map((key) => (
                  <th key={key} scope="col" className="ev-table__num">
                    {getSpec(key).label}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {groups.map((group) => (
                <tr key={group.label}>
                  <td
                    className={field === "model" ? "num" : undefined}
                    title={group.label}
                  >
                    {groupLabel(field, group.label)}
                  </td>
                  <td className="ev-table__num num">{group.runs.length}</td>

                  {COMPARED_KEYS.map((key) => (
                    <td key={key} className="ev-table__num num">
                      {formatMetric(key, meanOf(group.runs, key))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Pass Rate by Group"
        note="Mean"
        icon={Target}
        tone="green"
        span={6}
      >
        <RankedBars
          bars={groups.map((group, index) => ({
            label: groupLabel(field, group.label),
            value: meanOf(group.runs, "pass_rate"),
            color: colorAt(index),
          }))}
          formatValue={(value) => `${(value * 100).toFixed(1)}%`}
          max={1}
        />
      </Panel>

      <Panel
        title="Faithfulness by Group"
        note="Mean"
        icon={Target}
        tone="green"
        span={6}
      >
        <RankedBars
          bars={groups.map((group, index) => ({
            label: groupLabel(field, group.label),
            value: meanOf(group.runs, "faithfulness"),
            color: colorAt(index),
          }))}
          formatValue={(value) => value.toFixed(2)}
          max={1}
        />
      </Panel>
    </div>
  );
}
