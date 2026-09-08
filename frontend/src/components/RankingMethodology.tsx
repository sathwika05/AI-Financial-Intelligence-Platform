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
  ordering,
}: {
  weights: FactorMap | null | undefined;
  ordering?: string | null;
}) {
  // The rank order does not always follow these weights, and when it does
  // not the table shows a lower score above a higher one. That is correct
  // -- a question like "the five lowest P/E" is answered by the ORDER BY
  // the SQL layer wrote, and the composite below cannot reproduce it --
  // but it reads as a broken sort unless the page says which rule applied.
  const orderedBySql = ordering === "sql_order";
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

      {orderedBySql && (
        <p className="methodology__caption methodology__caption--order">
          This question was answered by a database query that already sorted
          the results, so the rank order comes from that query rather than
          from the score above. The scores are shown to explain each company,
          not to place it — which is why a lower score can appear higher in
          the list.
        </p>
      )}
    </div>
  );
}
