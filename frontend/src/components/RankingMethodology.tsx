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
 * hard-coded.
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
            >
              <div className="methodology__head">
                <span className="methodology__factor">
                  <span
                    className="methodology__swatch"
                    style={{
                      background: `var(--factor-${factor}, var(--accent))`,
                    }}
                  />
                  {factorLabel(factor)}
                </span>
                <span className="methodology__weight num">
                  {formatWeight(weight)}
                </span>
              </div>

              <span className="methodology__bar" aria-hidden="true">
                <span
                  className="methodology__bar-fill"
                  style={{
                    width: `${toWidthPercent(weight)}%`,
                    background: `var(--factor-${factor}, var(--accent))`,
                  }}
                />
              </span>

              {FACTOR_NOTES[factor] && (
                <span className="methodology__note">{FACTOR_NOTES[factor]}</span>
              )}
            </li>
          );
        })}
      </ul>

      <p className="methodology__caption">
        Each company receives a score from 0 to 1 on every factor. The factors
        are combined using the weights above, which the analysis sets per
        question based on the evidence available.
      </p>
    </div>
  );
}
