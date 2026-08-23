import {
  Activity,
  BarChart3,
  CheckCircle2,
  CircleDollarSign,
  ExternalLink,
  Gauge,
  GitCompareArrows,
  Network,
  Filter,
  Layers3,
  Search,
  Sparkles,
  Target,
  TriangleAlert,
} from "lucide-react";
import type { RunMetrics } from "../api";
import {
  formatDate,
  formatDateTime,
  formatDuration,
  formatLatencyCompact,
  parseModelSnapshot,
  questionSetLabel,
  retrievalLabel,
  shortRunId,
  titleCase,
} from "../format";
import { readMetric } from "../metrics";
import { DonutChart, GroupedBarChart, LineChart } from "../components/charts";
import {
  EmptyState,
  Field,
  KpiTile,
  MetricRow,
  Panel,
  StatusPill,
  UnavailablePanel,
} from "../components/primitives";
import { SERIES } from "../palette";
import { PerQuestionPanel } from "./PerQuestionView";
import { ROUTE_CARDS, RoutePerformanceCards } from "./RoutePerformance";
import { NodeLatencyPanel } from "./NodeLatency";
import { ToolSummaryPanel } from "./ToolSummary";

/**
 * The landing view: one run in full, with every figure carrying its change
 * against the previous completed run so a regression is visible without
 * opening the comparison screen.
 */

const CHART_RUN_LIMIT = 12;

/**
 * Slice colours and the sub-label the reference puts under "Hybrid". Keyed by
 * the route names the backend emits (see aggregation.CANONICAL_ROUTES).
 */
const ROUTE_STYLE: Record<string, { color: string; detail?: string }> = {
  "SQL Only": { color: "#3689e8" },
  "Vector Only": { color: "#21c36c" },
  Hybrid: { color: "#f49a0b", detail: "(SQL + Vector + API)" },
  Unclassified: { color: "#8296a4" },
};

function RouteDistributionPanel({
  distribution,
  onNavigate,
}: {
  distribution: Record<string, number>;
  onNavigate: (view: string) => void;
}) {
  // Canonical routes first, in the reference's order; anything the backend
  // adds later still renders, after them.
  const order = ["SQL Only", "Vector Only", "Hybrid"];

  const slices = [
    ...order.filter((route) => route in distribution),
    ...Object.keys(distribution).filter((route) => !order.includes(route)),
  ]
    // A zero "Unclassified" bucket is noise; a zero real route is information.
    .filter((route) => order.includes(route) || distribution[route] > 0)
    .map((route) => ({
      label: route,
      value: distribution[route] ?? 0,
      color: ROUTE_STYLE[route]?.color ?? "#8296a4",
      detail: ROUTE_STYLE[route]?.detail,
    }));

  const total = slices.reduce((sum, slice) => sum + slice.value, 0);

  return (
    <Panel
      title="Execution Route Distribution"
      note="(by Actual Route)"
      icon={GitCompareArrows}
      tone="blue"
      span={3}
      link={{
        label: "View Route Analysis",
        onClick: () => onNavigate("retrieval"),
      }}
    >
      <DonutChart
        slices={slices}
        centerValue={String(total)}
        centerLabel={total === 1 ? "Question" : "Questions"}
        // Sized so the ring and its legend sit side by side in a quarter of
        // the grid, as they do in the reference.
        size={140}
        thickness={18}
      />
    </Panel>
  );
}

function RunHeader({ run }: { run: RunMetrics }) {
  const tiers = parseModelSnapshot(run.model);

  return (
    <header className="ev-runhead">
      <div className="ev-runhead__identity">
        <span className="ev-runhead__eyebrow">Benchmark Run</span>

        <h1 className="ev-runhead__title">{shortRunId(run.run_id)}</h1>

        <StatusPill status={run.status} />

        {/* No endpoint reports the workspace or project, so this opens
            LangSmith rather than a deep link that may be wrong. */}
        <a
          className="ev-runhead__trace"
          href="https://smith.langchain.com/"
          target="_blank"
          rel="noreferrer noopener"
        >
          View in LangSmith
          <ExternalLink size={12} />
        </a>
      </div>

      <div className="ev-runhead__facts">
        <Field label="Started" value={formatDateTime(run.created_at)} />
        <Field
          label="Duration"
          value={formatDuration(run.created_at, run.completed_at)}
        />
        <Field label="Questions" value={String(run.total_requests)} />
        <Field label="Provider" value={run.provider_name} />
        <Field label="Dataset" value={run.dataset} />
        <Field label="Retrieval" value={retrievalLabel(run.retrieval_mode)} />
        <Field
          label="Question Set"
          value={questionSetLabel(run.question_set)}
        />
        <Field label="K" value={run.k == null ? null : String(run.k)} />
      </div>

      {tiers.length > 0 && (
        <div className="ev-runhead__models">
          {tiers.map((tier) => (
            <span key={tier.tier} className="ev-tier">
              <span className="ev-tier__name">{tier.tier}</span>
              <span className="ev-tier__model">{tier.model}</span>
            </span>
          ))}
        </div>
      )}

      {run.error_message && (
        <p className="ev-runhead__error">{run.error_message}</p>
      )}
    </header>
  );
}

export function SummaryView({
  run,
  previous,
  runs,
  onNavigate,
}: {
  run: RunMetrics | null;
  previous: RunMetrics | null;
  runs: RunMetrics[];
  onNavigate: (view: string) => void;
}) {
  if (!run) {
    return (
      <EmptyState
        title="No benchmark runs yet"
        detail="Queue one with Run Benchmark above. Results appear here as soon as the run finishes."
      />
    );
  }

  // The list arrives newest-first; charts read left-to-right in time order.
  const history = runs
    .filter((entry) => entry.status === "completed")
    .slice(0, CHART_RUN_LIMIT)
    .reverse();

  const categories = history.map((entry) => formatDate(entry.created_at));

  const total = run.total_requests;

  /** "18 / 20 Passed" — the count behind a rate, as the reference shows. */
  const countOf = (rate: number | null, noun: string): string | undefined =>
    rate == null || total === 0
      ? undefined
      : `${Math.round(rate * total)} / ${total} ${noun}`;

  return (
    <>
      <RunHeader run={run} />

      <div className="ev-kpirow">
        <KpiTile
          metricKey="total_requests"
          current={total}
          previous={readMetric(previous, "total_requests")}
          icon={Layers3}
          tone="violet"
          footer={
            run.status === "completed"
              ? "100% Completed"
              : titleCase(run.status)
          }
        />
        <KpiTile
          metricKey="pass_rate"
          current={readMetric(run, "pass_rate")}
          previous={readMetric(previous, "pass_rate")}
          icon={CheckCircle2}
          tone="green"
          footer={countOf(run.pass_rate, "Passed")}
        />
        <KpiTile
          metricKey="route_accuracy"
          current={readMetric(run, "route_accuracy")}
          previous={readMetric(previous, "route_accuracy")}
          icon={Target}
          tone="blue"
          footer={countOf(run.route_accuracy, "Correct")}
        />
        <KpiTile
          metricKey="faithfulness"
          current={readMetric(run, "faithfulness")}
          previous={readMetric(previous, "faithfulness")}
          icon={Activity}
          tone="violet"
          label="Faithfulness (Avg)"
        />
        <KpiTile
          metricKey="context_precision"
          current={readMetric(run, "context_precision")}
          previous={readMetric(previous, "context_precision")}
          icon={Sparkles}
          tone="amber"
          label="Context Precision (Avg)"
        />
        <KpiTile
          metricKey="context_recall"
          current={readMetric(run, "context_recall")}
          previous={readMetric(previous, "context_recall")}
          icon={Search}
          tone="cyan"
          label="Context Recall (Avg)"
        />
      </div>

      {/* The panel order below follows the design reference exactly:
          route row, latency row, analysis row, per-question results.
          Metrics that used to have their own cards here — answer grounding,
          routing, SQL, cost — live on the Metrics and Trend screens. */}
      <div className="ev-grid">
        {run.route_distribution && (
          <RouteDistributionPanel
            distribution={run.route_distribution}
            onNavigate={onNavigate}
          />
        )}

        {run.route_performance && (
          <RoutePerformanceCards
            performance={run.route_performance}
            onNavigate={onNavigate}
          />
        )}

        {run.node_latency && Object.keys(run.node_latency).length > 0 ? (
          <NodeLatencyPanel nodeLatency={run.node_latency} />
        ) : (
          <UnavailablePanel
            span={4}
            icon={Network}
            title="Latency by Node (All Routes)"
            reason="This run predates the graph timing instrumentation, so it carries no per-node breakdown. Runs recorded from now on will show one bar per stage."
          />
        )}

        <Panel
          title="Latency Distribution"
          note="(All Routes)"
          icon={Gauge}
          tone="violet"
          span={4}
          link={{
            label: "View Percentiles",
            onClick: () => onNavigate("trends"),
          }}
        >
          <GroupedBarChart
            series={[
              { label: "p50", color: SERIES.indigo },
              { label: "p95", color: SERIES.violet },
              { label: "p99", color: SERIES.amber },
            ]}
            groups={[
              {
                label: "All Routes",
                values: [run.p50_latency, run.p95_latency, run.p99_latency],
              },
              // Only routes this run actually exercised.
              ...ROUTE_CARDS.filter(
                (card) => run.route_performance?.[card.route]?.count,
              ).map((card) => {
                const block = run.route_performance?.[card.route] ?? {};

                return {
                  label: card.route,
                  values: [
                    block.p50_latency ?? null,
                    block.p95_latency ?? null,
                    block.p99_latency ?? null,
                  ],
                };
              }),
            ]}
            formatValue={formatLatencyCompact}
          />
        </Panel>

        <Panel
          title="Cost & Tokens Over Time"
          note="Per run"
          icon={CircleDollarSign}
          tone="amber"
          span={4}
          link={{
            label: "View Cost Analysis",
            onClick: () => onNavigate("trends"),
          }}
        >
          {history.length > 1 ? (
            <LineChart
              categories={categories}
              series={[
                {
                  label: "Cost (USD)",
                  color: SERIES.violet,
                  values: history.map((entry) => entry.total_cost),
                },
                {
                  // Scaled to thousands so it shares an axis with cost
                  // without flattening it; the legend says so.
                  label: "Tokens (K)",
                  color: SERIES.teal,
                  values: history.map((entry) =>
                    entry.total_tokens == null
                      ? null
                      : entry.total_tokens / 1000,
                  ),
                },
              ]}
              formatValue={(value) => value.toFixed(2)}
            />
          ) : (
            <p className="ev-note">
              Two completed runs are needed before a trend means anything. Runs
              recorded before usage tracking existed carry no cost or token
              figures and leave a gap in the line.
            </p>
          )}
        </Panel>

        <UnavailablePanel
          span={3}
          icon={Filter}
          title="Retrieval Pipeline Overview"
          reason="Stage counts are not recorded. The retrieval layer does not report how many candidates survive metadata filtering, BM25, vector search, RRF fusion and reranking, so the funnel has no source."
        />

        {run.tool_summary && <ToolSummaryPanel summary={run.tool_summary} />}

        <Panel
          title="Hallucination Analysis"
          note="Grounding"
          icon={TriangleAlert}
          tone="amber"
          span={3}
          link={{
            label: "View Error Analysis",
            onClick: () => onNavigate("errors"),
          }}
        >
          <MetricRow
            metricKey="hallucination_rate"
            current={readMetric(run, "hallucination_rate")}
            previous={readMetric(previous, "hallucination_rate")}
          />
          <MetricRow
            metricKey="faithfulness"
            current={readMetric(run, "faithfulness")}
            previous={readMetric(previous, "faithfulness")}
          />
          <MetricRow
            metricKey="noise_sensitivity"
            current={readMetric(run, "noise_sensitivity")}
            previous={readMetric(previous, "noise_sensitivity")}
          />
          <MetricRow
            metricKey="context_entity_recall"
            current={readMetric(run, "context_entity_recall")}
            previous={readMetric(previous, "context_entity_recall")}
          />

          <p className="ev-note" style={{ marginTop: 8 }}>
            Claim-level counts — unsupported claims, missing citations, invalid
            tickers — are not produced by any evaluator.
          </p>
        </Panel>

        <Panel
          title="Ranking Performance"
          note={`(Top K = ${run.k ?? "—"})`}
          icon={BarChart3}
          tone="blue"
          span={3}
          link={{
            label: "View Ranking Analysis",
            onClick: () => onNavigate("metrics"),
          }}
        >
          {(["precision_at_k", "recall_at_k", "ndcg_at_k", "mrr"] as const).map(
            (key) => (
              <MetricRow
                key={key}
                metricKey={key}
                current={readMetric(run, key)}
                previous={readMetric(previous, key)}
              />
            ),
          )}
        </Panel>

        <PerQuestionPanel run={run} />
      </div>
    </>
  );
}
