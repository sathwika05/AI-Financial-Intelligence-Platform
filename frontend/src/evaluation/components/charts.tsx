import { useElementWidth } from "../useElementWidth";

/**
 * Charts, drawn by hand in SVG.
 *
 * The dashboard needs three shapes — a trend line, a bar column and a ranked
 * bar list — over at most a few dozen points. A charting library would be the
 * single largest dependency in the bundle for that, so the scales are computed
 * here instead.
 *
 * The line chart draws at its measured pixel width rather than scaling a fixed
 * viewBox, so axis labels stay the same size whether the chart sits in a
 * four-column panel or across the full grid.
 */

/** Used until the first measurement lands, and as a floor for narrow panels. */
const FALLBACK_WIDTH = 480;

export interface LineSeries {
  label: string;
  color: string;
  /** One entry per category; null breaks the line rather than plotting zero. */
  values: (number | null)[];
}

interface Scale {
  min: number;
  max: number;
}

/** A little headroom above the data, and a floor at zero for rates and cost. */
function computeScale(series: LineSeries[], zeroBased: boolean): Scale {
  const values = series
    .flatMap((entry) => entry.values)
    .filter((value): value is number => value != null);

  if (values.length === 0) {
    return { min: 0, max: 1 };
  }

  const dataMax = Math.max(...values);
  const dataMin = Math.min(...values);

  if (dataMax === dataMin) {
    // A flat series would otherwise divide by a zero range.
    return { min: zeroBased ? 0 : dataMin * 0.9, max: dataMax * 1.1 || 1 };
  }

  const padding = (dataMax - dataMin) * 0.12;

  return {
    // Without a zero floor the lowest point would sit exactly on the axis,
    // so the fitted scale gets breathing room at both ends.
    min: zeroBased ? 0 : dataMin - padding,
    max: dataMax + padding,
  };
}

export function LineChart({
  categories,
  series,
  formatValue,
  height = 220,
  zeroBased = true,
}: {
  categories: string[];
  series: LineSeries[];
  formatValue: (value: number) => string;
  height?: number;
  zeroBased?: boolean;
}) {
  const [containerRef, measuredWidth] = useElementWidth<HTMLElement>();

  const scale = computeScale(series, zeroBased);
  const range = scale.max - scale.min || 1;

  const gridValues = [0, 0.25, 0.5, 0.75, 1].map(
    (fraction) => scale.min + fraction * range,
  );

  // The gutter is sized to the widest y label so "$0.0040" is not clipped and
  // "0.25" does not leave a wide empty margin.
  const longestLabel = Math.max(
    ...gridValues.map((value) => formatValue(value).length),
  );

  const padding = {
    top: 14,
    right: 16,
    bottom: 28,
    left: Math.min(84, 16 + longestLabel * 6.2),
  };

  const chartWidth = Math.max(measuredWidth || FALLBACK_WIDTH, 260);
  const plotWidth = chartWidth - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  // A single category has no interval to divide, so it is pinned mid-plot.
  const stepX =
    categories.length > 1 ? plotWidth / (categories.length - 1) : 0;

  const xFor = (index: number) =>
    categories.length > 1
      ? padding.left + index * stepX
      : padding.left + plotWidth / 2;

  const yFor = (value: number) =>
    padding.top + plotHeight - ((value - scale.min) / range) * plotHeight;

  /** Consecutive non-null runs become separate paths, so gaps stay gaps. */
  const buildSegments = (values: (number | null)[]): string[] => {
    const segments: string[] = [];
    let current: string[] = [];

    values.forEach((value, index) => {
      if (value == null) {
        if (current.length > 0) {
          segments.push(current.join(" "));
          current = [];
        }
        return;
      }

      const command = current.length === 0 ? "M" : "L";
      current.push(`${command}${xFor(index)},${yFor(value)}`);
    });

    if (current.length > 0) {
      segments.push(current.join(" "));
    }

    return segments;
  };

  // Roughly 54px per date label; anything denser collides.
  const maxLabels = Math.max(2, Math.floor(plotWidth / 54));
  const labelStride = Math.max(1, Math.ceil(categories.length / maxLabels));

  return (
    <figure className="ev-chart" ref={containerRef}>
      <svg
        viewBox={`0 0 ${chartWidth} ${height}`}
        width={chartWidth}
        height={height}
        className="ev-chart__svg"
        role="img"
        aria-label={`Trend of ${series.map((s) => s.label).join(", ")}`}
      >
        {gridValues.map((value) => (
          <g key={value}>
            <line
              x1={padding.left}
              x2={chartWidth - padding.right}
              y1={yFor(value)}
              y2={yFor(value)}
              className="ev-chart__grid"
            />
            <text
              x={padding.left - 10}
              y={yFor(value)}
              className="ev-chart__axis-label"
              textAnchor="end"
              dominantBaseline="middle"
            >
              {formatValue(value)}
            </text>
          </g>
        ))}

        {categories.map((category, index) =>
          index % labelStride === 0 ? (
            <text
              key={`${category}-${index}`}
              x={xFor(index)}
              y={height - 8}
              className="ev-chart__axis-label"
              textAnchor="middle"
            >
              {category}
            </text>
          ) : null,
        )}

        {series.map((entry) => (
          <g key={entry.label}>
            {buildSegments(entry.values).map((path, index) => (
              <path
                key={index}
                d={path}
                fill="none"
                stroke={entry.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}

            {entry.values.map((value, index) =>
              value == null ? null : (
                <circle
                  key={index}
                  cx={xFor(index)}
                  cy={yFor(value)}
                  r={3}
                  fill={entry.color}
                >
                  <title>{`${entry.label} · ${categories[index]} · ${formatValue(value)}`}</title>
                </circle>
              ),
            )}
          </g>
        ))}
      </svg>

      <figcaption className="ev-chart__legend">
        {series.map((entry) => (
          <span key={entry.label} className="ev-chart__legend-item">
            <span
              className="ev-chart__swatch"
              style={{ background: entry.color }}
              aria-hidden="true"
            />
            {entry.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
  /** Optional second line under the label in the legend. */
  detail?: string;
}

/**
 * Ring chart with a total in the middle.
 *
 * Drawn as stroked arcs on one circle rather than filled wedge paths: a
 * `stroke-dasharray` per slice needs only the running total to place each
 * arc, and the ring thickness is then a single stroke-width.
 */
export function DonutChart({
  slices,
  centerValue,
  centerLabel,
  size = 168,
  thickness = 21,
}: {
  slices: DonutSlice[];
  centerValue: string;
  centerLabel: string;
  size?: number;
  thickness?: number;
}) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);

  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;

  let consumed = 0;

  return (
    <figure className="ev-donut">
      <div className="ev-donut__ring" style={{ width: size, height: size }}>
        <svg
          viewBox={`0 0 ${size} ${size}`}
          width={size}
          height={size}
          role="img"
          aria-label={`Execution route distribution across ${total} questions`}
        >
          {/* Rotated so the first slice starts at twelve o'clock. */}
          <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              className="ev-donut__track"
              strokeWidth={thickness}
            />

            {total > 0 &&
              slices.map((slice) => {
                const length = (slice.value / total) * circumference;
                const offset = -consumed;

                consumed += length;

                if (slice.value === 0) {
                  return null;
                }

                return (
                  <circle
                    key={slice.label}
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke={slice.color}
                    strokeWidth={thickness}
                    strokeDasharray={`${length} ${circumference - length}`}
                    strokeDashoffset={offset}
                  >
                    <title>{`${slice.label}: ${slice.value} of ${total}`}</title>
                  </circle>
                );
              })}
          </g>
        </svg>

        <div className="ev-donut__center">
          <strong>{centerValue}</strong>
          <span>{centerLabel}</span>
        </div>
      </div>

      <figcaption className="ev-donut__legend">
        {slices.map((slice) => (
          <div key={slice.label} className="ev-donut__legend-row">
            <span
              className="ev-donut__swatch"
              style={{ background: slice.color }}
              aria-hidden="true"
            />

            <span className="ev-donut__legend-text">
              <span>{slice.label}</span>
              {slice.detail && (
                <span className="ev-donut__legend-detail">{slice.detail}</span>
              )}
            </span>

            <strong className="ev-donut__legend-value">
              {slice.value}
              {total > 0 && ` (${Math.round((slice.value / total) * 100)}%)`}
            </strong>
          </div>
        ))}
      </figcaption>
    </figure>
  );
}

export interface GroupedSeries {
  label: string;
  color: string;
}

export interface BarGroup {
  label: string;
  /** One value per series, in the same order as `series`. */
  values: (number | null)[];
}

/**
 * Clustered columns — one cluster per category, one bar per series.
 *
 * Built in CSS rather than SVG because each bar carries a value label above
 * it, and flex handles that far more simply than positioned SVG text.
 */
export function GroupedBarChart({
  series,
  groups,
  formatValue,
  height = 190,
}: {
  series: GroupedSeries[];
  groups: BarGroup[];
  formatValue: (value: number) => string;
  height?: number;
}) {
  const all = groups
    .flatMap((group) => group.values)
    .filter((value): value is number => value != null);

  const max = all.length > 0 ? Math.max(...all) : 1;

  return (
    <figure className="ev-grouped">
      <div className="ev-grouped__plot" style={{ height }}>
        {groups.map((group) => (
          <div key={group.label} className="ev-grouped__group">
            <div className="ev-grouped__bars">
              {group.values.map((value, index) => (
                <div key={series[index].label} className="ev-grouped__slot">
                  <span className="ev-grouped__value">
                    {value == null ? "—" : formatValue(value)}
                  </span>

                  <span
                    className="ev-grouped__bar"
                    style={{
                      // A measured-but-tiny bar still gets a visible sliver.
                      height:
                        value == null || max === 0
                          ? 0
                          : `${Math.max((value / max) * 100, 2)}%`,
                      background: series[index].color,
                    }}
                    title={`${group.label} · ${series[index].label} · ${
                      value == null ? "no data" : formatValue(value)
                    }`}
                  />
                </div>
              ))}
            </div>

            <span className="ev-grouped__label">{group.label}</span>
          </div>
        ))}
      </div>

      <figcaption className="ev-chart__legend">
        {series.map((entry) => (
          <span key={entry.label} className="ev-chart__legend-item">
            <span
              className="ev-chart__swatch"
              style={{ background: entry.color }}
              aria-hidden="true"
            />
            {entry.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export interface Bar {
  label: string;
  value: number | null;
  color?: string;
}

/** Vertical columns — used where the categories are few and comparable. */
export function BarChart({
  bars,
  formatValue,
  height = 200,
}: {
  bars: Bar[];
  formatValue: (value: number) => string;
  height?: number;
}) {
  const values = bars
    .map((bar) => bar.value)
    .filter((value): value is number => value != null);

  const max = values.length > 0 ? Math.max(...values) : 1;

  return (
    <figure className="ev-bars" style={{ height }}>
      {bars.map((bar) => {
        const ratio = bar.value == null || max === 0 ? 0 : bar.value / max;

        return (
          <div key={bar.label} className="ev-bars__column">
            <span className="ev-bars__value num">
              {bar.value == null ? "—" : formatValue(bar.value)}
            </span>

            <div className="ev-bars__track">
              <div
                className="ev-bars__fill"
                style={{
                  // A measured-but-tiny bar still gets a visible sliver.
                  height: `${bar.value == null ? 0 : Math.max(ratio * 100, 2)}%`,
                  background: bar.color,
                }}
              />
            </div>

            <span className="ev-bars__label">{bar.label}</span>
          </div>
        );
      })}
    </figure>
  );
}

/** Horizontal bars — used where labels are long and the list is ranked. */
export function RankedBars({
  bars,
  formatValue,
  max,
}: {
  bars: Bar[];
  formatValue: (value: number) => string;
  /** Pin the scale (1 for scores) so rows stay comparable across panels. */
  max?: number;
}) {
  const values = bars
    .map((bar) => bar.value)
    .filter((value): value is number => value != null);

  const ceiling = max ?? (values.length > 0 ? Math.max(...values) : 1);

  return (
    <div className="ev-ranked">
      {bars.map((bar) => {
        const ratio =
          bar.value == null || ceiling === 0 ? 0 : bar.value / ceiling;

        return (
          <div key={bar.label} className="ev-ranked__row">
            <span className="ev-ranked__label" title={bar.label}>
              {bar.label}
            </span>

            <span className="ev-ranked__track">
              <span
                className="ev-ranked__fill"
                style={{
                  width: `${Math.max(0, Math.min(1, ratio)) * 100}%`,
                  background: bar.color,
                }}
              />
            </span>

            <span className="ev-ranked__value num">
              {bar.value == null ? "—" : formatValue(bar.value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
