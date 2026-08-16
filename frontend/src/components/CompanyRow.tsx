import { useId, type CSSProperties } from "react";
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  FileText,
  Quote,
  Table2,
} from "lucide-react";
import { buildMetricItems } from "./MetricGrid";
import { CitationText } from "./CitationText";
import { CitedClaims, DetailedEvidenceGroups } from "./EvidenceList";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { ScoreSpine } from "./ScoreSpine";
import { Stat, StatRail } from "./Stat";
import { Warnings } from "./Warnings";
import { entryCitationIds, entryFacts, type CompanyEntry } from "../lib/entries";
import { formatRatioAsPercent, formatScore } from "../lib/format";
import {
  hasUnsupportedSentiment,
  matchLabel,
  matchStrength,
  readFlag,
  recommendationTone,
} from "../lib/labels";
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

/** Section heading inside the expanded panel. */
function PanelSection({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof FileText;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="row__block">
      <h4 className="row__block-title">
        <Icon size={13} className="row__block-icon" aria-hidden="true" />
        {title}
      </h4>
      {children}
    </section>
  );
}

/**
 * A single company in the ranking: scannable when collapsed, complete when
 * open. Expanding in place keeps the reader's position in the ranking, which
 * a modal or drawer takes away.
 *
 * The collapsed row answers the ranking questions in reading order — who,
 * on what figures, at what score, how strong a match — with limitations kept
 * deliberately quiet beneath.
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
  const match = matchLabel(facts.recommendation);
  const strength = matchStrength(facts.recommendation);
  const flags = facts.flags ?? [];
  const unverified = hasUnsupportedSentiment(flags)
    ? new Set(["sentiment"])
    : undefined;

  const rank = facts.rank ?? null;
  // Only the top three get emphasis; beyond that the ranking reads as a list.
  const podium = rank != null && rank <= 3 ? ` row--rank-${rank}` : "";

  return (
    <article
      className={`row${expanded ? " row--open" : ""}${podium}`}
      style={{ "--index": index } as CSSProperties}
    >
      <button
        type="button"
        className="row__head"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
      >
        <span className="row__rank">
          <span className="row__rank-value num">{rank ?? "—"}</span>
        </span>

        <span className="row__identity">
          <span className="row__ticker">{facts.ticker ?? facts.name}</span>
          <span className="row__name">{facts.name}</span>
        </span>

        {/* Fixed columns, not a flowing rail: P/E under P/E, EPS under EPS,
            all the way down the ranking. */}
        <StatRail columns={4}>
          {metrics.map((item) => (
            <Stat
              key={item.label}
              label={item.label}
              value={item.value}
              absent={item.value === "N/A"}
            />
          ))}
        </StatRail>

        <span className="row__score">
          <span className="row__score-figure">
            <span className="row__score-value num">
              {formatScore(facts.finalScore)}
            </span>
            <span className="row__score-label">Composite</span>
          </span>

          <ScoreSpine
            contributions={entry.ranked?.explainability?.contributions}
            scores={entry.ranked?.explainability?.scores}
            finalScore={facts.finalScore}
            size="sm"
            unverifiedFactors={unverified}
          />

          <span className="row__verdict">
            {match && (
              <span
                className={`row__match row__match--${tone}`}
                title={
                  facts.recommendation
                    ? `Model verdict: ${facts.recommendation}`
                    : undefined
                }
              >
                {strength != null && (
                  <span className="row__match-pips" aria-hidden="true">
                    {[0, 1, 2, 3].map((pip) => (
                      <span
                        key={pip}
                        className={`row__match-pip${
                          pip <= strength ? " row__match-pip--on" : ""
                        }`}
                      />
                    ))}
                  </span>
                )}
                {match}
              </span>
            )}

            {facts.confidence != null && (
              <span className="row__confidence" title="Model confidence in this company's analysis.">
                <span className="row__confidence-label">Confidence</span>
                <span className="row__confidence-value num">
                  {formatRatioAsPercent(facts.confidence)}
                </span>
              </span>
            )}
          </span>
        </span>

        <ChevronDown size={16} className="row__chevron" aria-hidden="true" />
      </button>

      {/* One limitation stays visible when collapsed; the rest open below. */}
      {!expanded && flags.length > 0 && (
        <p className="row__caveat">
          <AlertTriangle size={11} className="row__caveat-icon" aria-hidden="true" />
          <span className="row__caveat-text">{readFlag(flags[0]).label}</span>
          {flags.length > 1 && (
            <span className="row__caveat-more">+{flags.length - 1} more</span>
          )}
        </p>
      )}

      {expanded && (
        <div className="row__panel" id={panelId}>
          <div className="row__panel-grid">
            <div className="row__panel-col">
              <PanelSection icon={Quote} title="Why this company ranked here">
                {facts.summary ? (
                  <CitationText
                    text={facts.summary}
                    knownIds={entryCitationIds(entry)}
                    onSelectCitation={onSelectCitation}
                  />
                ) : (
                  <p className="row__note">
                    The analysis returned no written explanation for this
                    company.
                  </p>
                )}
              </PanelSection>

              <PanelSection icon={Table2} title="Financial metrics">
                <StatRail columns={4}>
                  {metrics.map((item) => (
                    <Stat
                      key={item.label}
                      label={item.label}
                      value={item.value}
                      absent={item.value === "N/A"}
                    />
                  ))}
                </StatRail>
              </PanelSection>

              <PanelSection icon={FileText} title="Supporting evidence">
                <CitedClaims
                  evidence={entry.report?.evidence}
                  highlightId={highlightCitation}
                />
                <DetailedEvidenceGroups
                  evidence={entry.ranked?.evidence}
                  highlightId={highlightCitation}
                />
              </PanelSection>
            </div>

            <div className="row__panel-col">
              <PanelSection icon={BarChart3} title="Factor breakdown">
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
              </PanelSection>

              {flags.length > 0 && (
                <PanelSection icon={AlertTriangle} title="Evidence limitations">
                  <Warnings flags={flags} />
                </PanelSection>
              )}
            </div>
          </div>
        </div>
      )}
    </article>
  );
}
