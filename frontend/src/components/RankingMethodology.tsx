import type { FactorMap } from "../api/types";
import { formatWeight, toWidthPercent } from "../lib/format";
import { factorLabel, orderFactors } from "../lib/labels";
import "./RankingMethodology.css";

const FACTOR_NOTES: Record<string, string> = {
  valuation: "Price relative to earnings",
  growth: "Revenue and earnings trajectory",
  relevance: "Match to the question asked",
  sentiment: "Tone of supporting documents",
};

/**
 * The weighting behind this ranking, read from the response.
 *
 * Weights are decided per question by the backend and have been observed to
 * change between queries, including dropping to zero, so nothing here is
 * hard-coded. Presented as one compact row per factor — swatch, name, bar,
 * weight — so the mix reads as a single analytical block.
 */
export function RankingMethodology({
  weights,
}: {
  weights: FactorMap | null | undefined;
}) {
  const entries = weights ? orderFactors(Object.keys(weights)) : [];

  if (entries.length === 0) {
    return (
      <p className="methodology__empty">
        The ranking weights for this question were not returned.
      </p>
    );
  }

  return (
    <div className="methodology">
      <ul className="methodology__list">
        {entries.map((factor) => {
          const weight = weights?.[factor];
          const unused = typeof weight === "number" && weight === 0;

          return (
            <li
              key={factor}
              className={`methodology__item${
                unused ? " methodology__item--unused" : ""
              }`}
              title={FACTOR_NOTES[factor]}
            >
              <span
                className="methodology__swatch"
                style={{
                  background: `var(--factor-${factor}, var(--accent))`,
                }}
                aria-hidden="true"
              />

              <span className="methodology__factor">{factorLabel(factor)}</span>

              <span className="methodology__bar" aria-hidden="true">
                <span
                  className="methodology__bar-fill"
                  style={{
                    width: `${toWidthPercent(weight)}%`,
                    background: `var(--factor-${factor}, var(--accent))`,
                  }}
                />
              </span>

              <span className="methodology__weight num">
                {formatWeight(weight)}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="methodology__caption">
        Each company scores 0–1 per factor. Factors are combined using these
        weights, which the analysis sets per question.
      </p>
    </div>
  );
}
