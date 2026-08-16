/**
 * Series colours.
 *
 * Chosen to stay separable on the dashboard's near-black ground and to keep
 * their meaning stable across views: a metric drawn in violet on the summary
 * chart is violet again on the trend screen. Kept in TypeScript rather than
 * CSS because SVG fills are set as attributes, not classes.
 */
export const SERIES = {
  indigo: "#3689e8",
  violet: "#7b50dd",
  teal: "#17bfd0",
  amber: "#f49a0b",
  rose: "#ff6168",
  sky: "#5ca2f4",
  lime: "#22cf70",
} as const;

export const SERIES_CYCLE = [
  SERIES.indigo,
  SERIES.teal,
  SERIES.violet,
  SERIES.amber,
  SERIES.sky,
  SERIES.rose,
  SERIES.lime,
];

export function colorAt(index: number): string {
  return SERIES_CYCLE[index % SERIES_CYCLE.length];
}
