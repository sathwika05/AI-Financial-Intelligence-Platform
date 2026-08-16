import type { CSSProperties } from "react";
import type { FactorMap } from "../api/types";
import { formatScore } from "../lib/format";
import { factorLabel, orderFactors } from "../lib/labels";
import "./ScoreSpine.css";

export interface ScoreSpineProps {
  contributions: FactorMap | null | undefined;
  /** Backend final score, marked on the same 0–1 track. */
  finalScore?: number | null;
  size?: "sm" | "md" | "lg";
  /** Factors whose evidence the backend flagged as unsupported. */
  unverifiedFactors?: ReadonlySet<string>;
  showScale?: boolean;
}

interface Segment {
  factor: string;
  value: number;
  unverified: boolean;
}

function buildSegments(
  contributions: FactorMap | null | undefined,
  unverifiedFactors: ReadonlySet<string>,
): Segment[] {
  if (!contributions) {
    return [];
  }

  return orderFactors(Object.keys(contributions))
    .map((factor) => {
      const value = contributions[factor];

      return {
        factor,
        value: typeof value === "number" && Number.isFinite(value) ? value : 0,
        unverified: unverifiedFactors.has(factor),
      };
    })
    .filter((segment) => segment.value > 0);
}

const EMPTY_SET: ReadonlySet<string> = new Set<string>();

/**
 * The stacked contribution bar used at every scale of the product: a compact
 * bar on company cards, a cell in the comparison table, and the annotated
 * breakdown in company details.
 *
 * Contributions are drawn on a 0–1 track. The final score is marked
 * separately rather than implied by the bar width, because the backend's
 * final score does not always equal the sum of the listed contributions.
 */
export function ScoreSpine({
  contributions,
  finalScore,
  size = "md",
  unverifiedFactors = EMPTY_SET,
  showScale = false,
}: ScoreSpineProps) {
  const segments = buildSegments(contributions, unverifiedFactors);

  if (segments.length === 0) {
    return (
      <div className={`spine spine--${size} spine--empty`}>
        <div className="spine__track" aria-hidden="true" />
        <p className="spine__fallback">Factor breakdown unavailable</p>
      </div>
    );
  }

  const markerPosition =
    typeof finalScore === "number" && Number.isFinite(finalScore)
      ? Math.max(0, Math.min(1, finalScore)) * 100
      : null;

  const description = segments
    .map((segment) => `${factorLabel(segment.factor)} ${segment.value.toFixed(3)}`)
    .join(", ");

  return (
    <div className={`spine spine--${size}`}>
      <div
        className="spine__track"
        role="img"
        aria-label={`Weighted factor contributions: ${description}`}
      >
        {segments.map((segment) => (
          <span
            key={segment.factor}
            className={`spine__segment${
              segment.unverified ? " spine__segment--unverified" : ""
            }`}
            style={
              {
                width: `${Math.max(0, Math.min(1, segment.value)) * 100}%`,
                "--segment-color": `var(--factor-${segment.factor}, var(--accent))`,
              } as CSSProperties
            }
            title={`${factorLabel(segment.factor)}: ${segment.value.toFixed(3)}${
              segment.unverified ? " (evidence unverified)" : ""
            }`}
          />
        ))}

        {markerPosition !== null && (
          <span
            className="spine__marker"
            style={{ left: `${markerPosition}%` }}
            title={`Final score ${formatScore(finalScore)}`}
          />
        )}
      </div>

      {showScale && (
        <div className="spine__scale eyebrow">
          <span>0.00</span>
          <span>Final score {formatScore(finalScore)}</span>
          <span>1.00</span>
        </div>
      )}
    </div>
  );
}

export interface SpineLegendProps {
  factors: string[];
  unverifiedFactors?: ReadonlySet<string>;
}

export function SpineLegend({
  factors,
  unverifiedFactors = EMPTY_SET,
}: SpineLegendProps) {
  return (
    <ul className="spine-legend">
      {orderFactors(factors).map((factor) => (
        <li key={factor} className="spine-legend__item">
          <span
            className={`spine-legend__swatch${
              unverifiedFactors.has(factor)
                ? " spine-legend__swatch--unverified"
                : ""
            }`}
            style={
              {
                "--segment-color": `var(--factor-${factor}, var(--accent))`,
              } as CSSProperties
            }
          />
          {factorLabel(factor)}
        </li>
      ))}
    </ul>
  );
}
