import type { ReactNode } from "react";
import "./Stat.css";

/**
 * A compact financial data point: muted label, strong figure.
 *
 * This shape repeats in the collapsed company row, the expanded detail and
 * the comparison view, so it lives here once. Deliberately not a card — a
 * page of boxed metrics reads as a dashboard, whereas a rail of aligned
 * figures reads as a research terminal.
 */
export function Stat({
  label,
  value,
  absent = false,
  tone = "default",
  title,
}: {
  label: string;
  value: ReactNode;
  /** Renders the value as unavailable rather than as a figure. */
  absent?: boolean;
  tone?: "default" | "muted" | "positive" | "caution";
  title?: string;
}) {
  return (
    <div className="stat" title={title}>
      <dt className="stat__label">{label}</dt>
      <dd
        className={`stat__value num stat__value--${tone}${
          absent ? " stat__value--absent" : ""
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

/** A horizontal run of data points sharing one baseline. */
export function StatRail({
  children,
  columns,
}: {
  children: ReactNode;
  /** Fixed column count; omit to let the rail flow. */
  columns?: number;
}) {
  return (
    <dl
      className={`stat-rail${columns ? " stat-rail--fixed" : ""}`}
      style={columns ? { "--stat-columns": columns } as React.CSSProperties : undefined}
    >
      {children}
    </dl>
  );
}
