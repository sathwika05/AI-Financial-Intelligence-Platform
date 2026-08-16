import type { ComponentType } from "react";
import { Database, Target, Zap } from "lucide-react";
import { formatMetric, getSpec, type MetricKey } from "../metrics";
import { formatLatency, formatPercent } from "../format";
import { Panel, type PanelTone } from "../components/primitives";

/**
 * Per-route performance cards, in the reference's order: SQL, Vector, Hybrid.
 *
 * The backend stores every canonical metric for every route, so which ones a
 * card shows is decided here — each route gets the metrics that actually mean
 * something for it. A SQL-only question has no context recall; a vector-only
 * question has no SQL equivalence.
 */

type IconComponent = ComponentType<{ size?: number; className?: string }>;

interface RouteCardSpec {
  /** Route key as emitted by the backend. */
  route: string;
  title: string;
  icon: IconComponent;
  tone: PanelTone;
  keys: MetricKey[];
}

/** Order matters: this is the sequence the cards render in. */
export const ROUTE_CARDS: RouteCardSpec[] = [
  {
    route: "SQL Only",
    title: "SQL Route Performance",
    icon: Database,
    tone: "blue",
    keys: [
      "sql_accuracy",
      "sql_equivalence",
      "intent_accuracy",
      "precision_at_k",
      "recall_at_k",
    ],
  },
  {
    route: "Vector Only",
    title: "Vector Route Performance",
    icon: Target,
    tone: "green",
    keys: [
      "faithfulness",
      "response_relevancy",
      "context_precision",
      "context_recall",
      "precision_at_k",
      "recall_at_k",
    ],
  },
  {
    route: "Hybrid",
    title: "Hybrid Route Performance",
    icon: Zap,
    tone: "amber",
    keys: [
      "tool_accuracy",
      "tool_f1",
      "faithfulness",
      "sql_accuracy",
      "market_accuracy",
      "context_precision",
    ],
  },
];

function RouteRow({
  metricKey,
  value,
}: {
  metricKey: MetricKey;
  value: number | null;
}) {
  const spec = getSpec(metricKey);

  return (
    <div className="ev-metric-row">
      <span className="ev-metric-row__label" title={spec.hint}>
        {spec.label}
      </span>
      <span className="ev-metric-row__value">
        {formatMetric(metricKey, value)}
      </span>
      <span className="ev-metric-row__delta" />
    </div>
  );
}

export function RoutePerformanceCards({
  performance,
  onNavigate,
}: {
  performance: Record<string, Record<string, number | null | undefined>>;
  onNavigate: (view: string) => void;
}) {
  return (
    <>
      {ROUTE_CARDS.map((card) => {
        const block = performance[card.route];
        const count = block?.count ?? 0;

        // A route no question took still gets its card. Dropping it would
        // leave the row short of twelve columns, pulling the next row's
        // panels up into it and breaking the layout for every panel below.
        if (!block || !count) {
          return (
            <Panel
              key={card.route}
              title={card.title}
              note="(0 Questions)"
              icon={card.icon}
              tone={card.tone}
              span={3}
            >
              <p className="ev-note">
                No question in this run took the {card.route.toLowerCase()}{" "}
                route, so there is nothing to average.
              </p>
            </Panel>
          );
        }

        // Metrics no evaluator produced for this route are dropped rather
        // than shown as a column of dashes.
        const measured = card.keys.filter(
          (key) => typeof block[key] === "number",
        );

        return (
          <Panel
            key={card.route}
            title={card.title}
            note={`(${count} ${count === 1 ? "Question" : "Questions"})`}
            icon={card.icon}
            tone={card.tone}
            span={3}
            link={{
              label: "View Details",
              onClick: () => onNavigate("metrics"),
            }}
          >
            <div className="ev-metric-row">
              <span className="ev-metric-row__label">Pass Rate</span>
              <span className="ev-metric-row__value">
                {formatPercent(
                  typeof block.pass_rate === "number" ? block.pass_rate : null,
                )}
              </span>
              <span className="ev-metric-row__delta" />
            </div>

            <div className="ev-metric-row">
              <span className="ev-metric-row__label">Avg Latency</span>
              <span className="ev-metric-row__value">
                {formatLatency(
                  typeof block.avg_latency_ms === "number"
                    ? block.avg_latency_ms
                    : null,
                )}
              </span>
              <span className="ev-metric-row__delta" />
            </div>

            {measured.map((key) => (
              <RouteRow
                key={key}
                metricKey={key}
                value={block[key] as number}
              />
            ))}

            {measured.length === 0 && (
              <p className="ev-note">
                No evaluator reported a score for this route.
              </p>
            )}
          </Panel>
        );
      })}
    </>
  );
}
