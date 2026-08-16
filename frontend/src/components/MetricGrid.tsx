import type { CSSProperties } from "react";
import type { KeyMetrics } from "../api/types";
import { formatGrowth, formatMarketCap, formatRatio } from "../lib/format";
import "./MetricGrid.css";

export interface MetricItem {
  label: string;
  value: string;
  hint?: string;
}

/**
 * Build the standard four financial figures from either metric shape.
 *
 * `key_metrics` (final report) and `metrics` (ranked companies) represent
 * revenue growth differently; formatGrowth handles both.
 */
export function buildMetricItems(
  metrics: KeyMetrics | null | undefined,
): MetricItem[] {
  return [
    { label: "P/E Ratio", value: formatRatio(metrics?.pe_ratio) },
    { label: "Revenue Growth", value: formatGrowth(metrics?.revenue_growth) },
    { label: "EPS", value: formatRatio(metrics?.eps) },
    { label: "Market Cap", value: formatMarketCap(metrics?.market_cap) },
  ];
}

export function MetricGrid({
  metrics,
  columns = 4,
}: {
  metrics: KeyMetrics | null | undefined;
  columns?: number;
}) {
  const items = buildMetricItems(metrics);

  return (
    <dl
      className="metric-grid"
      style={{ "--metric-columns": columns } as CSSProperties}
    >
      {items.map((item) => (
        <div className="metric" key={item.label}>
          <dt className="metric__label eyebrow">{item.label}</dt>
          <dd
            className={`metric__value num${
              item.value === "N/A" ? " metric__value--absent" : ""
            }`}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
