import type { MetricValue } from "../api/types";

/** Shown whenever the backend has no value. Never substitute zero. */
export const NOT_AVAILABLE = "N/A";

/**
 * Coerce an API figure to a number.
 *
 * Returns null for null/undefined/empty/non-numeric input so callers can
 * render N/A rather than silently turning missing data into 0.
 */
export function toNumber(value: MetricValue | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }

  const cleaned = value.replace(/[$,\s%]/g, "").trim();

  if (cleaned === "") {
    return null;
  }

  const parsed = Number(cleaned);

  return Number.isFinite(parsed) ? parsed : null;
}

/** True when the raw value already carries a percent sign, e.g. "85.2%". */
function isPreformattedPercent(value: MetricValue | undefined): value is string {
  return typeof value === "string" && value.includes("%");
}

/**
 * Revenue growth, from either representation the API uses.
 *
 * `final_report.top_companies[].key_metrics.revenue_growth` is already a
 * formatted string ("85.2%") and must not be scaled again.
 * `ranked_companies[].metrics.revenue_growth` is a decimal (0.852) and is
 * scaled to "85.2%".
 */
export function formatGrowth(value: MetricValue | undefined): string {
  if (isPreformattedPercent(value)) {
    return value.trim();
  }

  const parsed = toNumber(value);

  if (parsed === null) {
    return NOT_AVAILABLE;
  }

  return `${(parsed * 100).toFixed(1)}%`;
}

/** A 0–1 ratio rendered as a whole percentage, e.g. 0.71 -> "71%". */
export function formatRatioAsPercent(
  value: number | null | undefined,
  digits = 0,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NOT_AVAILABLE;
  }

  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * Market capitalisation with financial magnitude suffixes.
 * 5453358039040 -> "$5.45T", 102543073280 -> "$102.54B".
 */
export function formatMarketCap(value: MetricValue | undefined): string {
  const parsed = toNumber(value);

  if (parsed === null) {
    return NOT_AVAILABLE;
  }

  const sign = parsed < 0 ? "-" : "";
  const magnitude = Math.abs(parsed);

  const units: Array<{ limit: number; suffix: string }> = [
    { limit: 1e12, suffix: "T" },
    { limit: 1e9, suffix: "B" },
    { limit: 1e6, suffix: "M" },
    { limit: 1e3, suffix: "K" },
  ];

  for (const { limit, suffix } of units) {
    if (magnitude >= limit) {
      return `${sign}$${(magnitude / limit).toFixed(2)}${suffix}`;
    }
  }

  return `${sign}$${magnitude.toFixed(2)}`;
}

/** P/E, EPS and similar ratios at sensible financial precision. */
export function formatRatio(
  value: MetricValue | undefined,
  digits = 2,
): string {
  const parsed = toNumber(value);

  return parsed === null ? NOT_AVAILABLE : parsed.toFixed(digits);
}

/** A 0–1 score shown at 2dp, e.g. 0.721 -> "0.72". */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NOT_AVAILABLE;
  }

  return value.toFixed(2);
}

/** Weight 0.364 -> "36%" for the ranking-methodology display. */
export function formatWeight(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NOT_AVAILABLE;
  }

  return `${Math.round(value * 100)}%`;
}

/** Clamp a 0–1 value into a CSS width percentage. */
export function toWidthPercent(value: number | null | undefined): number {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.min(1, value)) * 100;
}
