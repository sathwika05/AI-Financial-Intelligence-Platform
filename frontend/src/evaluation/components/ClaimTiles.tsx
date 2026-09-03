import { useEffect, useState } from "react";
import { FileCheck2, ShieldAlert, ShieldCheck, UserCheck } from "lucide-react";
import { getClaimSummary, type ClaimSummary } from "../api";

/**
 * The four claim cards on the summary row.
 *
 * Deliberately not KpiTiles. Those read from RunMetrics through the metric
 * catalogue, and these come from the claims endpoint — widening that type
 * to carry them would change what every other screen reads for the sake of
 * four numbers on one row. The markup matches .ev-kpi so they sit in the
 * row without any layout change.
 *
 * Renders nothing at all when a run has no claims, which every run from
 * before claim auditing existed does not. Four zeroes would read as a
 * measured result rather than as an absent one.
 */
export function ClaimTiles({ runId }: { runId: string }) {
  const [summary, setSummary] = useState<ClaimSummary | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    getClaimSummary(runId, controller.signal)
      .then(setSummary)
      // A failure here must not take the summary row with it: the claim
      // cards are additional to the run's own metrics.
      .catch(() => undefined);

    return () => controller.abort();
  }, [runId]);

  if (!summary || summary.total_claims === 0) {
    return null;
  }

  return (
    <>
      <Tile
        icon={<ShieldCheck size={15} />}
        tone="green"
        label="Claim Support Rate"
        value={pct(summary.claim_support_rate)}
        foot={`${summary.supported} / ${summary.total_claims} supported`}
        hint="Share of factual claims the run's own retrieved evidence supports. Hedged statements are excluded before scoring."
      />

      <Tile
        icon={<ShieldAlert size={15} />}
        tone="amber"
        label="Unsupported Fact Rate"
        value={pct(summary.unsupported_fact_rate)}
        foot={`${summary.unsupported} unsupported · ${summary.insufficient_evidence} no evidence`}
        hint="Claims the evidence contradicts or is silent on. Numeric claims are strict: the figure must appear in the evidence or follow from it arithmetically."
      />

      <Tile
        icon={<UserCheck size={15} />}
        tone="blue"
        label="Human-Validated Claims"
        value={`${summary.validated_claims}`}
        foot={
          summary.validated_claims
            ? `of ${summary.total_claims} claims`
            : "none labelled yet"
        }
        hint="Claims a person has labelled by hand on the Evaluator Validation screen."
      />

      <Tile
        icon={<FileCheck2 size={15} />}
        tone="violet"
        label="Evaluator Agreement"
        value={summary.validated_claims ? pct(summary.agreement) : "—"}
        foot={
          summary.validated_claims
            ? `${summary.false_negatives} missed · ${summary.false_positives} false alarms`
            : "label some claims to measure"
        }
        hint="How often the evaluator's label matched the human's. Missed means a claim a person called unsupported that the evaluator accepted."
      />
    </>
  );
}

function Tile({
  icon,
  tone,
  label,
  value,
  foot,
  hint,
}: {
  icon: React.ReactNode;
  tone: string;
  label: string;
  value: string;
  foot: string;
  hint: string;
}) {
  return (
    <article className="ev-kpi">
      <header className="ev-kpi__head">
        <span className={`ev-kpi__icon ev-kpi__icon--${tone}`}>{icon}</span>

        <span className="ev-kpi__label" title={label}>
          {label}
        </span>

        <span className="ev-kpi__info" title={hint} aria-label={hint}>
          i
        </span>
      </header>

      <p className="ev-kpi__value">{value}</p>

      <footer className="ev-kpi__foot">
        <span>{foot}</span>
      </footer>
    </article>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
