import type { ComponentType, ReactNode } from "react";
import { EM_DASH } from "../format";
import {
  computeDelta,
  formatDelta,
  formatMetric,
  getSpec,
  type MetricKey,
} from "../metrics";

/**
 * The small parts every view is assembled from.
 *
 * Cards, stat rows and deltas repeat across eight screens, so their markup
 * lives here once. Anything with layout of its own stays in its view.
 */

type IconComponent = ComponentType<{ size?: number; className?: string }>;

export type PanelTone = "blue" | "green" | "amber" | "violet";

export function Panel({
  title,
  note,
  icon: Icon,
  tone,
  action,
  link,
  children,
  span,
}: {
  title: string;
  note?: string;
  icon?: IconComponent;
  tone?: PanelTone;
  action?: ReactNode;
  /** Bottom rail linking to the view that expands on this card. */
  link?: { label: string; onClick: () => void };
  children: ReactNode;
  /** Column span on the 12-column dashboard grid. */
  span?: number;
}) {
  return (
    <section
      className="ev-panel"
      style={span ? { gridColumn: `span ${span}` } : undefined}
    >
      <header className="ev-panel__head">
        {Icon && (
          <Icon
            size={15}
            className={`ev-panel__icon${tone ? ` ev-panel__icon--${tone}` : ""}`}
          />
        )}
        <h2 className="ev-panel__title">{title}</h2>
        {note && <span className="ev-panel__note">{note}</span>}
        {action && <div className="ev-panel__action">{action}</div>}
      </header>

      <div className="ev-panel__body">{children}</div>

      {link && (
        <button
          type="button"
          className="ev-panel__link"
          onClick={link.onClick}
        >
          {link.label} →
        </button>
      )}
    </section>
  );
}

export function DeltaBadge({
  metricKey,
  current,
  previous,
}: {
  metricKey: MetricKey;
  current: number | null;
  previous: number | null;
}) {
  const delta = computeDelta(metricKey, current, previous);

  if (!delta || delta.change === 0) {
    return null;
  }

  const tone =
    delta.improved == null ? "flat" : delta.improved ? "up" : "down";

  return (
    <span className={`ev-delta ev-delta--${tone}`}>
      <span aria-hidden="true">{delta.change > 0 ? "↑" : "↓"}</span>
      <span>{formatDelta(metricKey, delta.change)}</span>
    </span>
  );
}

export function MetricRow({
  metricKey,
  current,
  previous,
}: {
  metricKey: MetricKey;
  current: number | null;
  previous?: number | null;
}) {
  const spec = getSpec(metricKey);

  return (
    <div className="ev-metric-row">
      <span className="ev-metric-row__label" title={spec.hint}>
        {spec.label}
      </span>

      <span className="ev-metric-row__value">
        {formatMetric(metricKey, current)}
      </span>

      <span className="ev-metric-row__delta">
        <DeltaBadge
          metricKey={metricKey}
          current={current}
          previous={previous ?? null}
        />
      </span>
    </div>
  );
}

export type KpiTone = "violet" | "green" | "blue" | "amber" | "cyan";

export function KpiTile({
  metricKey,
  current,
  previous,
  icon: Icon,
  tone,
  label,
  footer,
}: {
  metricKey: MetricKey;
  current: number | null;
  previous: number | null;
  icon: IconComponent;
  tone: KpiTone;
  /** Overrides the catalog label, e.g. "Faithfulness (Avg)". */
  label?: string;
  /** Replaces the delta line, e.g. "18 / 20 Passed". */
  footer?: string;
}) {
  const spec = getSpec(metricKey);

  // "vs prev run" is only meaningful next to a change; on an unchanged or
  // unmeasurable metric it would caption an empty space.
  const delta = computeDelta(metricKey, current, previous);
  const hasDelta = delta != null && delta.change !== 0;

  return (
    <article className="ev-kpi">
      <header className="ev-kpi__head">
        <span className={`ev-kpi__icon ev-kpi__icon--${tone}`}>
          <Icon size={15} />
        </span>

        <span className="ev-kpi__label" title={label ?? spec.label}>
          {label ?? spec.label}
        </span>

        {spec.hint && (
          <span className="ev-kpi__info" title={spec.hint} aria-label={spec.hint}>
            i
          </span>
        )}
      </header>

      <p className="ev-kpi__value">{formatMetric(metricKey, current)}</p>

      <footer className="ev-kpi__foot">
        {footer ? (
          <span>{footer}</span>
        ) : hasDelta ? (
          <>
            <DeltaBadge
              metricKey={metricKey}
              current={current}
              previous={previous}
            />
            <span>vs prev run</span>
          </>
        ) : (
          <span>{previous == null ? "no prior run" : "unchanged"}</span>
        )}
      </footer>
    </article>
  );
}

export function StatusPill({ status }: { status: string }) {
  return <span className={`ev-status ev-status--${status}`}>{status}</span>;
}

export function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="ev-field">
      <span className="ev-field__label">{label}</span>
      <span className="ev-field__value">{value || EM_DASH}</span>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="ev-empty">
      <p className="ev-empty__title">{title}</p>
      <p className="ev-empty__detail">{detail}</p>
      {action}
    </div>
  );
}

/**
 * Shown where the design reference has a panel but the API has no data behind
 * it. Naming the missing source is more useful than an empty box or, worse, a
 * plausible-looking number.
 */
export function UnavailablePanel({
  title,
  reason,
  icon,
  span,
}: {
  title: string;
  reason: string;
  icon?: IconComponent;
  span?: number;
}) {
  return (
    <Panel title={title} note="No data" icon={icon} span={span}>
      <p className="ev-unavailable">{reason}</p>
    </Panel>
  );
}

/** A 0–1 score drawn as a track, for scanning a column of metrics quickly. */
export function ScoreBar({ value }: { value: number | null }) {
  const width = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;

  return (
    <span className="ev-scorebar" aria-hidden="true">
      <span className="ev-scorebar__fill" style={{ width: `${width}%` }} />
    </span>
  );
}
