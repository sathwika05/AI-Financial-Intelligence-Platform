import { useId, type CSSProperties } from "react";
import { buildMetricItems } from "./MetricGrid";
import { CitationText } from "./CitationText";
import { CitedClaims, DetailedEvidenceGroups } from "./EvidenceList";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { ScoreSpine } from "./ScoreSpine";
import { Warnings } from "./Warnings";
import { entryCitationIds, entryFacts, type CompanyEntry } from "../lib/entries";
import { formatRatioAsPercent, formatScore } from "../lib/format";
import { hasUnsupportedSentiment, readFlag, recommendationTone } from "../lib/labels";
import "./CompanyRow.css";

export interface CompanyRowProps {
  entry: CompanyEntry;
  /** Position in the list, used to stagger the entrance. */
  index: number;
  expanded: boolean;
  onToggle: () => void;
  highlightCitation: string | null;
  onSelectCitation: (citationId: string) => void;
}

/**
 * A single company in the ranking: scannable when collapsed, complete when
 * open. Expanding in place keeps the reader's position in the ranking, which
 * a modal or drawer takes away.
 */
export function CompanyRow({
  entry,
  index,
  expanded,
  onToggle,
  highlightCitation,
  onSelectCitation,
}: CompanyRowProps) {
  const panelId = useId();
  const facts = entryFacts(entry);
  const metrics = buildMetricItems(facts.metrics);
  const tone = recommendationTone(facts.recommendation);
  const flags = facts.flags ?? [];
  const unverified = hasUnsupportedSentiment(flags)
    ? new Set(["sentiment"])
    : undefined;

  return (
    <article
      className={`row${expanded ? " row--open" : ""}`}
      style={{ "--index": index } as CSSProperties}
    >
      <button
        type="button"
        className="row__head"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
      >
        <span className="row__rank num">{facts.rank ?? "—"}</span>

        <span className="row__identity">
          <span className="row__ticker num">{facts.ticker ?? facts.name}</span>
          <span className="row__name">{facts.name}</span>
        </span>

        <span className="row__score">
          <span className="row__score-value num">
            {formatScore(facts.finalScore)}
          </span>
          <span className="row__spine">
            <ScoreSpine
              contributions={entry.ranked?.explainability?.contributions}
              finalScore={facts.finalScore}
              size="sm"
              unverifiedFactors={unverified}
            />
          </span>
        </span>

        {facts.recommendation && (
          <span className={`row__assessment row__assessment--${tone}`}>
            {facts.recommendation}
          </span>
        )}

        <span className="row__chevron" aria-hidden="true" />
      </button>

      <dl className="row__metrics">
        {metrics.map((item) => (
          <div className="row__metric" key={item.label}>
            <dt className="row__metric-label">{item.label}</dt>
            <dd
              className={`row__metric-value num${
                item.value === "N/A" ? " row__metric-value--absent" : ""
              }`}
            >
              {item.value}
            </dd>
          </div>
        ))}

        {facts.confidence != null && (
          <div className="row__metric row__metric--end">
            <dt className="row__metric-label">Confidence</dt>
            <dd className="row__metric-value row__metric-value--muted num">
              {formatRatioAsPercent(facts.confidence)}
            </dd>
          </div>
        )}
      </dl>

      {/* Limitations stay visible when collapsed; the rest opens below. */}
      {!expanded && flags.length > 0 && (
        <p className="row__caveat">
          <span className="row__caveat-mark" aria-hidden="true" />
          {readFlag(flags[0]).label}
          {flags.length > 1 && (
            <span className="row__caveat-more">+{flags.length - 1} more</span>
          )}
        </p>
      )}

      {expanded && (
        <div className="row__panel" id={panelId}>
          <div className="row__panel-grid">
            <div className="row__panel-col">
              {facts.summary && (
                <CitationText
                  text={facts.summary}
                  knownIds={entryCitationIds(entry)}
                  onSelectCitation={onSelectCitation}
                />
              )}

              {flags.length > 0 && (
                <section className="row__block">
                  <h4 className="row__block-title">Evidence limitations</h4>
                  <Warnings flags={flags} />
                </section>
              )}

              <section className="row__block">
                <h4 className="row__block-title">Cited in this analysis</h4>
                <CitedClaims
                  evidence={entry.report?.evidence}
                  highlightId={highlightCitation}
                />
              </section>
            </div>

            <div className="row__panel-col">
              <section className="row__block">
                <h4 className="row__block-title">Why this ranking</h4>

                {entry.ranked ? (
                  <ScoreBreakdown
                    explainability={entry.ranked.explainability}
                    finalScore={facts.finalScore}
                    unverifiedFactors={unverified}
                  />
                ) : (
                  <p className="row__note">
                    This company was not part of the scored comparison set, so
                    no factor breakdown is available for it.
                  </p>
                )}
              </section>

              <section className="row__block">
                <h4 className="row__block-title">Supporting sources</h4>
                <DetailedEvidenceGroups
                  evidence={entry.ranked?.evidence}
                  highlightId={highlightCitation}
                />
              </section>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}
