import type { FinalReport } from "../api/types";
import { formatRatioAsPercent } from "../lib/format";
import {
  evidenceQualityLabel,
  evidenceQualityTone,
  intentLabel,
} from "../lib/labels";
import "./AnalysisSummary.css";

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
      <div className="summary__body">
        <span className="eyebrow">Analysis</span>

        {report.query_summary ? (
          <p className="summary__text">{report.query_summary}</p>
        ) : (
          <p className="summary__text summary__text--absent">
            The analysis returned no written summary for this question.
          </p>
        )}
      </div>

      <div className="summary__meta">
        {intent && <span className="chip">{intent}</span>}

        {report.overall_confidence != null && (
          <span className="chip" title="How confident the model is in this analysis.">
            Model confidence
            <span className="chip__value">
              {formatRatioAsPercent(report.overall_confidence)}
            </span>
          </span>
        )}

        {quality && (
          <span
            className={`chip chip--${qualityTone}`}
            title="How much supporting evidence was available for this analysis."
          >
            Evidence quality
            <span className="chip__value">{quality}</span>
          </span>
        )}

        {checksRan && (
          <span
            className="chip"
            title="The analysis was checked against its supporting evidence before being returned. Any limitations are listed with each company."
          >
            Analysis checks completed
          </span>
        )}

        {provider && <span className="summary__provider">via {provider}</span>}
      </div>
    </section>
  );
}
