import type { Explainability } from "../api/types";
import { formatScore, formatWeight, toWidthPercent } from "../lib/format";
import { factorLabel, orderFactors } from "../lib/labels";
import { ScoreSpine, SpineLegend } from "./ScoreSpine";
import "./ScoreBreakdown.css";

export interface ScoreBreakdownProps {
  explainability: Explainability | null | undefined;
  finalScore?: number | null;
  unverifiedFactors?: ReadonlySet<string>;
}

const EMPTY_SET: ReadonlySet<string> = new Set<string>();

/**
 * Factor-by-factor explanation of a ranking, built only from fields the
 * backend returns: scores, weights and weighted contributions.
 *
 * The final score is displayed as returned and never recomputed here.
 */
export function ScoreBreakdown({
  explainability,
  finalScore,
  unverifiedFactors = EMPTY_SET,
}: ScoreBreakdownProps) {
  const scores = explainability?.scores ?? {};
  const weights = explainability?.weights ?? {};
  const contributions = explainability?.contributions ?? {};

  const factors = orderFactors([
    ...new Set([
      ...Object.keys(scores),
      ...Object.keys(weights),
      ...Object.keys(contributions),
    ]),
  ]);

  if (factors.length === 0) {
    return (
      <p className="breakdown__empty">
        A factor breakdown was not returned for this company.
      </p>
    );
  }

  return (
    <div className="breakdown">
      <div className="breakdown__spine">
        <ScoreSpine
          contributions={contributions}
          finalScore={finalScore ?? explainability?.final_score}
          size="lg"
          unverifiedFactors={unverifiedFactors}
          showScale
        />
        <SpineLegend factors={factors} unverifiedFactors={unverifiedFactors} />
      </div>

      <table className="breakdown__table">
        <thead>
          <tr>
            <th scope="col">Factor</th>
            <th scope="col" className="is-numeric">
              Score
            </th>
            <th scope="col" className="is-numeric">
              Weight
            </th>
            <th scope="col" className="is-numeric">
              Contribution
            </th>
          </tr>
        </thead>

        <tbody>
          {factors.map((factor) => {
            const score = scores[factor];
            const unverified = unverifiedFactors.has(factor);

            return (
              <tr key={factor}>
                <th scope="row">
                  <span className="breakdown__factor">
                    <span
                      className={`breakdown__swatch${
                        unverified ? " breakdown__swatch--unverified" : ""
                      }`}
                      style={{ background: `var(--factor-${factor}, var(--accent))` }}
                    />
                    {factorLabel(factor)}
                    {unverified && (
                      <span
                        className="breakdown__caveat"
                        title="The backend flagged this factor's supporting evidence as unverified."
                      >
                        evidence unverified
                      </span>
                    )}
                  </span>

                  <span className="breakdown__meter" aria-hidden="true">
                    <span
                      className="breakdown__meter-fill"
                      style={{
                        width: `${toWidthPercent(score)}%`,
                        background: `var(--factor-${factor}, var(--accent))`,
                      }}
                    />
                  </span>
                </th>

                <td className="is-numeric num">{formatScore(score)}</td>
                <td className="is-numeric num">{formatWeight(weights[factor])}</td>
                <td className="is-numeric num breakdown__contribution">
                  {formatScore(contributions[factor])}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {explainability?.interpretation && (
        <p className="breakdown__interpretation">
          {explainability.interpretation}
        </p>
      )}
    </div>
  );
}
