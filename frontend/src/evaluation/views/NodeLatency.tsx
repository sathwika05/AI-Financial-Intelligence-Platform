import { Network } from "lucide-react";
import { formatLatencyCompact } from "../format";
import { BarChart } from "../components/charts";
import { Panel } from "../components/primitives";
import { SERIES } from "../palette";

/**
 * Latency by graph node.
 *
 * The order below is the pipeline's own execution order, so the chart reads
 * left to right as the question travels through the graph. Nodes the backend
 * did not report are omitted rather than drawn at zero — a question routed
 * away from the reranker never entered it, which is different from entering
 * it instantly.
 */
const NODE_ORDER = [
  "intent",
  "planner",
  "retrieval",
  "reranker",
  "scoring",
  "analysis",
  "reviewer",
];

const NODE_LABEL: Record<string, string> = {
  intent: "Intent",
  planner: "Planner",
  retrieval: "Retrieval",
  reranker: "Reranker",
  scoring: "Scoring",
  analysis: "Analysis",
  reviewer: "Reviewer",
};

export function NodeLatencyPanel({
  nodeLatency,
  span = 4,
}: {
  nodeLatency: Record<string, Record<string, number | null | undefined>>;
  span?: number;
}) {
  const present = [
    ...NODE_ORDER.filter((node) => node in nodeLatency),
    ...Object.keys(nodeLatency).filter((node) => !NODE_ORDER.includes(node)),
  ];

  const bars = present.map((node) => ({
    label: NODE_LABEL[node] ?? node,
    value: nodeLatency[node]?.avg_latency_ms ?? null,
    color: SERIES.violet,
  }));

  // Re-runs happen when the reviewer routes a question back to an earlier
  // stage, so the count is worth stating rather than implying one pass each.
  const reruns = present.filter(
    (node) => (nodeLatency[node]?.executions ?? 0) > 0,
  ).length;

  return (
    <Panel
      title="Latency by Node"
      note="(All Routes)"
      icon={Network}
      tone="violet"
      span={span}
    >
      {bars.length === 0 ? (
        <p className="ev-note">
          No node timings were recorded for this run.
        </p>
      ) : (
        <>
          <BarChart bars={bars} formatValue={formatLatencyCompact} height={188} />
          <p className="ev-note" style={{ marginTop: 8 }}>
            Mean wall-clock time per stage across {reruns} instrumented node
            {reruns === 1 ? "" : "s"}. A stage the reviewer sent a question
            back to is counted on every pass.
          </p>
        </>
      )}
    </Panel>
  );
}
