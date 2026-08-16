import type { RunMetrics } from "./api";
import {
  formatCost,
  formatCount,
  formatLatency,
  formatPercent,
  formatScore,
} from "./format";

/**
 * The metric catalog.
 *
 * One entry per numeric field the evaluation endpoints return, carrying the
 * three things every panel needs: how to name it, how to render it, and which
 * direction counts as an improvement. Panels below are just orderings over
 * these keys, which keeps a metric's meaning defined in exactly one place.
 */

export type MetricKey = keyof Pick<
  RunMetrics,
  | "pass_rate"
  | "route_accuracy"
  | "intent_accuracy"
  | "hallucination_rate"
  | "faithfulness"
  | "response_relevancy"
  | "context_precision"
  | "context_recall"
  | "context_entity_recall"
  | "noise_sensitivity"
  | "precision_at_k"
  | "recall_at_k"
  | "mrr"
  | "ndcg_at_k"
  | "sql_accuracy"
  | "sql_equivalence"
  | "tool_accuracy"
  | "tool_precision"
  | "tool_recall"
  | "tool_f1"
  | "market_accuracy"
  | "avg_latency_ms"
  | "p95_latency"
  | "p99_latency"
  | "cost_per_request"
  | "total_cost"
  | "total_tokens"
  | "total_requests"
>;

type MetricKind = "score" | "rate" | "latency" | "cost" | "count";

export interface MetricSpec {
  key: MetricKey;
  label: string;
  kind: MetricKind;
  /** Which way is better. Drives the colour of every delta on the screen. */
  direction: "higher" | "lower" | "neutral";
  hint?: string;
}

const SPECS: MetricSpec[] = [
  {
    key: "pass_rate",
    label: "Overall Pass Rate",
    kind: "rate",
    direction: "higher",
    hint: "Share of questions whose combined evaluator score cleared the pass threshold.",
  },
  {
    key: "route_accuracy",
    label: "Route Accuracy",
    kind: "rate",
    direction: "higher",
    hint: "How often the graph took the execution route the question expected.",
  },
  {
    key: "intent_accuracy",
    label: "Intent Accuracy",
    kind: "score",
    direction: "higher",
    hint: "Classifier agreement with the labelled intent.",
  },
  {
    key: "hallucination_rate",
    label: "Hallucination Rate",
    kind: "rate",
    direction: "lower",
    hint: "Claims unsupported by retrieved context. Derived as 1 − faithfulness when no explicit measure exists.",
  },

  {
    key: "faithfulness",
    label: "Faithfulness",
    kind: "score",
    direction: "higher",
    hint: "Are the answer's claims entailed by the retrieved context?",
  },
  {
    key: "response_relevancy",
    label: "Response Relevancy",
    kind: "score",
    direction: "higher",
    hint: "Does the answer address the question that was asked?",
  },
  {
    key: "context_precision",
    label: "Context Precision",
    kind: "score",
    direction: "higher",
    hint: "Proportion of retrieved context that was actually useful.",
  },
  {
    key: "context_recall",
    label: "Context Recall",
    kind: "score",
    direction: "higher",
    hint: "Proportion of the reference context that retrieval found.",
  },
  {
    key: "context_entity_recall",
    label: "Context Entity Recall",
    kind: "score",
    direction: "higher",
    hint: "Coverage of the entities the reference answer depends on.",
  },
  {
    key: "noise_sensitivity",
    label: "Noise Sensitivity",
    kind: "score",
    direction: "lower",
    hint: "How much irrelevant context degrades the answer.",
  },

  {
    key: "precision_at_k",
    label: "Precision@K",
    kind: "score",
    direction: "higher",
  },
  { key: "recall_at_k", label: "Recall@K", kind: "score", direction: "higher" },
  { key: "ndcg_at_k", label: "NDCG@K", kind: "score", direction: "higher" },
  {
    key: "mrr",
    label: "MRR",
    kind: "score",
    direction: "higher",
    hint: "Mean reciprocal rank of the first correct company.",
  },

  {
    key: "sql_accuracy",
    label: "SQL Result Accuracy",
    kind: "score",
    direction: "higher",
    hint: "Generated query returned the expected rows.",
  },
  {
    key: "sql_equivalence",
    label: "SQL Semantic Equivalence",
    kind: "score",
    direction: "higher",
    hint: "Generated query means the same thing as the reference query.",
  },

  {
    key: "tool_accuracy",
    label: "Tool Call Accuracy",
    kind: "score",
    direction: "higher",
  },
  {
    key: "tool_precision",
    label: "Tool Precision",
    kind: "score",
    direction: "higher",
  },
  {
    key: "tool_recall",
    label: "Tool Recall",
    kind: "score",
    direction: "higher",
  },
  { key: "tool_f1", label: "Tool F1", kind: "score", direction: "higher" },

  {
    key: "market_accuracy",
    label: "Market Data Accuracy",
    kind: "score",
    direction: "higher",
    hint: "Agreement between live market API values and the expected figures.",
  },

  {
    key: "avg_latency_ms",
    label: "Average Latency",
    kind: "latency",
    direction: "lower",
  },
  { key: "p95_latency", label: "P95 Latency", kind: "latency", direction: "lower" },
  { key: "p99_latency", label: "P99 Latency", kind: "latency", direction: "lower" },

  {
    key: "cost_per_request",
    label: "Cost per Question",
    kind: "cost",
    direction: "lower",
  },
  { key: "total_cost", label: "Total Cost", kind: "cost", direction: "neutral" },
  {
    key: "total_tokens",
    label: "Total Tokens",
    kind: "count",
    direction: "neutral",
    hint: "LLM tokens consumed across every call in this run, measured per call.",
  },
  {
    key: "total_requests",
    label: "Total Questions",
    kind: "count",
    direction: "neutral",
  },
];

const SPEC_BY_KEY = new Map<MetricKey, MetricSpec>(
  SPECS.map((spec) => [spec.key, spec]),
);

export function getSpec(key: MetricKey): MetricSpec {
  const spec = SPEC_BY_KEY.get(key);

  if (!spec) {
    throw new Error(`No metric spec registered for "${key}".`);
  }

  return spec;
}

export function formatMetric(
  key: MetricKey,
  value: number | null | undefined,
): string {
  switch (getSpec(key).kind) {
    case "rate":
      return formatPercent(value);
    case "latency":
      return formatLatency(value);
    case "cost":
      return formatCost(value);
    case "count":
      return formatCount(value);
    default:
      return formatScore(value);
  }
}

/** Panels are orderings over the catalog — see the comment at the top. */
export interface MetricPanelSpec {
  id: string;
  title: string;
  note: string;
  keys: MetricKey[];
}

export const PANELS: MetricPanelSpec[] = [
  {
    id: "grounding",
    title: "Answer Grounding",
    note: "RAGAS",
    keys: [
      "faithfulness",
      "response_relevancy",
      "context_precision",
      "context_recall",
      "context_entity_recall",
      "noise_sensitivity",
    ],
  },
  {
    id: "ranking",
    title: "Ranking Performance",
    note: "Top K",
    keys: ["precision_at_k", "recall_at_k", "ndcg_at_k", "mrr"],
  },
  {
    id: "routing",
    title: "Routing & Integrity",
    note: "Intent",
    keys: [
      "route_accuracy",
      "intent_accuracy",
      "hallucination_rate",
      "market_accuracy",
    ],
  },
  {
    id: "sql",
    title: "SQL Route",
    note: "Structured",
    keys: ["sql_accuracy", "sql_equivalence"],
  },
  {
    id: "tools",
    title: "Tool Execution",
    note: "Agent",
    keys: ["tool_accuracy", "tool_precision", "tool_recall", "tool_f1"],
  },
  {
    id: "latency",
    title: "Latency",
    note: "Per question",
    keys: ["avg_latency_ms", "p95_latency", "p99_latency"],
  },
  {
    id: "cost",
    title: "Cost",
    note: "USD",
    keys: ["total_cost", "cost_per_request", "total_tokens", "total_requests"],
  },
];

/** The six figures pinned above the fold. */
export const KPI_KEYS: MetricKey[] = [
  "total_requests",
  "pass_rate",
  "route_accuracy",
  "faithfulness",
  "context_precision",
  "context_recall",
];

export interface MetricDelta {
  /** Signed change in the metric's own units. */
  change: number;
  /** Whether the change moved in the metric's preferred direction. */
  improved: boolean | null;
}

export function computeDelta(
  key: MetricKey,
  current: number | null | undefined,
  previous: number | null | undefined,
): MetricDelta | null {
  if (current == null || previous == null) {
    return null;
  }

  const change = current - previous;
  const { direction } = getSpec(key);

  if (change === 0 || direction === "neutral") {
    return { change, improved: null };
  }

  return {
    change,
    improved: direction === "higher" ? change > 0 : change < 0,
  };
}

/** Deltas read in the metric's own units, so a rate delta reads in points. */
export function formatDelta(key: MetricKey, change: number): string {
  const sign = change > 0 ? "+" : "−";
  const magnitude = Math.abs(change);

  switch (getSpec(key).kind) {
    case "rate":
      return `${sign}${(magnitude * 100).toFixed(1)}pp`;
    case "latency":
      return `${sign}${formatLatency(magnitude)}`;
    case "cost":
      return `${sign}${formatCost(magnitude)}`;
    case "count":
      return `${sign}${formatCount(magnitude)}`;
    default:
      return `${sign}${magnitude.toFixed(2)}`;
  }
}

export function readMetric(
  run: RunMetrics | null | undefined,
  key: MetricKey,
): number | null {
  if (!run) {
    return null;
  }

  const value = run[key];

  return typeof value === "number" ? value : null;
}

/**
 * Runs arrive newest-first. "Previous" means the next older run that actually
 * finished — comparing against a queued or failed run would report a drop to
 * null as if it were a regression.
 */
export function findPreviousRun(
  runs: RunMetrics[],
  current: RunMetrics | null,
): RunMetrics | null {
  if (!current) {
    return null;
  }

  const index = runs.findIndex((run) => run.run_id === current.run_id);

  if (index < 0) {
    return null;
  }

  return (
    runs.slice(index + 1).find((run) => run.status === "completed") ?? null
  );
}

export function isTerminal(status: string): boolean {
  return status === "completed" || status === "failed";
}

/** Mean over the runs that reported the metric; null when none did. */
export function meanOf(runs: RunMetrics[], key: MetricKey): number | null {
  const values = runs
    .map((run) => readMetric(run, key))
    .filter((value): value is number => value != null);

  if (values.length === 0) {
    return null;
  }

  return values.reduce((total, value) => total + value, 0) / values.length;
}

export interface RunGroup {
  label: string;
  runs: RunMetrics[];
}

/**
 * Groups completed runs by one of their configuration fields, which is how
 * the comparison views are built: the endpoints expose no cross-run
 * aggregate, but every run carries the configuration it ran under.
 */
export function groupRuns(
  runs: RunMetrics[],
  field: "retrieval_mode" | "model" | "question_set" | "dataset",
): RunGroup[] {
  const groups = new Map<string, RunMetrics[]>();

  for (const run of runs) {
    if (run.status !== "completed") {
      continue;
    }

    const label = run[field]?.trim() || "unspecified";
    const existing = groups.get(label);

    if (existing) {
      existing.push(run);
    } else {
      groups.set(label, [run]);
    }
  }

  return [...groups.entries()]
    .map(([label, grouped]) => ({ label, runs: grouped }))
    .sort((a, b) => b.runs.length - a.runs.length);
}
