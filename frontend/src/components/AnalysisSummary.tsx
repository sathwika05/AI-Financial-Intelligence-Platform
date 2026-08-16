import { BadgeCheck, Gauge, Layers, ShieldCheck } from "lucide-react";
import type { FinalReport } from "../api/types";
import { formatRatioAsPercent } from "../lib/format";
import {
  evidenceQualityLabel,
  evidenceQualityTone,
  intentLabel,
} from "../lib/labels";
import "./AnalysisSummary.css";

/**
 * The analysis intelligence summary.
 *
 * The written conclusion is the one dominant element; everything else is
 * provenance for it and is set as a compact metadata strip beneath. The
 * chips carry semantic colour only on their value, so a row of them never
 * competes with the ranking below.
 */
export function AnalysisSummary({
  report,
  provider,
}: {
  report: FinalReport;
  provider?: string | null;
}) {
  const intent = intentLabel(report.intent);
  const quality = evidenceQualityLabel(report.evidence_quality);
  const qualityTone = evidenceQualityTone(report.evidence_quality);
  const checksRan = Boolean(report.review);

  return (
    <section className="summary panel">
      <span className="eyebrow summary__eyebrow">Analysis</span>

      {report.query_summary ? (
        <p className="summary__text">{report.query_summary}</p>
      ) : (
        <p className="summary__text summary__text--absent">
          The analysis returned no written summary for this question.
        </p>
      )}

      <div className="summary__meta">
        {intent && (
          <span className="chip chip--ai">
            <Layers size={12} className="chip__icon" aria-hidden="true" />
            {intent}
          </span>
        )}

        {report.overall_confidence != null && (
          <span
            className="chip chip--ai"
            title="How confident the model is in this analysis."
          >
            <Gauge size={12} className="chip__icon" aria-hidden="true" />
            Model confidence
            <span className="chip__value num">
              {formatRatioAsPercent(report.overall_confidence)}
            </span>
          </span>
        )}

        {quality && (
          <span
            className={`chip chip--${qualityTone}`}
            title="How much supporting evidence was available for this analysis."
          >
            <ShieldCheck size={12} className="chip__icon" aria-hidden="true" />
            Evidence quality
            <span className="chip__value">{quality}</span>
          </span>
        )}

        {checksRan && (
          <span
            className="chip"
            title="The analysis was checked against its supporting evidence before being returned. Any limitations are listed with each company."
          >
            <BadgeCheck size={12} className="chip__icon" aria-hidden="true" />
            Checks completed
          </span>
        )}

        {provider && <span className="summary__provider">via {provider}</span>}
      </div>
    </section>
  );
}
