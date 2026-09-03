import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import {
  getClaimSummary,
  getRunClaims,
  saveClaimLabel,
  type ClaimLabel,
  type ClaimRow,
  type ClaimSummary,
  type RunMetrics,
} from "../api";
import { shortRunId } from "../format";
import { EmptyState, Panel } from "../components/primitives";

/**
 * Evaluator validation: a human labels the same claims the judge did.
 *
 * Without this page the unsupported-fact rate is one more LLM's opinion.
 * With it there is a measured answer to "how often is the evaluator
 * right", and — the number worth reading first — how many fabrications it
 * waved through.
 *
 * The human label is stored beside the evaluator's, never over it. A
 * re-run replaces the judge's verdict and leaves the person's alone, so
 * agreement can be recomputed across runs.
 */

const LABELS: ClaimLabel[] = [
  "SUPPORTED",
  "UNSUPPORTED",
  "INSUFFICIENT_EVIDENCE",
];

const SHORT: Record<ClaimLabel, string> = {
  SUPPORTED: "Supported",
  UNSUPPORTED: "Unsupported",
  INSUFFICIENT_EVIDENCE: "Insufficient",
};

function LabelPill({ label }: { label: ClaimLabel | null }) {
  if (!label) return <span className="cl-pill cl-pill--none">Not labelled</span>;

  return (
    <span className={`cl-pill cl-pill--${label.toLowerCase()}`}>
      {SHORT[label]}
    </span>
  );
}

export function ValidationView({ run }: { run: RunMetrics | null }) {
  const runId = run?.run_id ?? null;

  const [rows, setRows] = useState<ClaimRow[]>([]);
  const [summary, setSummary] = useState<ClaimSummary | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!runId) return;

      // Set on every load, not only the first: without it the table claims
      // to be empty while a fetch for a newly selected run is in flight.
      setStatus("loading");

      try {
        const [claims, totals] = await Promise.all([
          getRunClaims(runId, {}, signal),
          getClaimSummary(runId, signal),
        ]);

        setRows(claims);
        setSummary(totals);
        setError(null);
        setStatus("ready");
      } catch (caught) {
        if ((caught as Error)?.name === "AbortError") return;

        setError((caught as Error)?.message ?? "Could not load claims.");
        setStatus("error");
      }
    },
    [runId],
  );

  useEffect(() => {
    const controller = new AbortController();

    load(controller.signal);

    return () => controller.abort();
  }, [load]);

  const label = async (claimId: number, next: ClaimLabel) => {
    setSaving(claimId);

    try {
      const updated = await saveClaimLabel(claimId, next);

      // Patched in place rather than refetching the list: a labelling
      // session is fifty rows long, and reloading would jump the reader
      // back to the top after every click.
      setRows((current) =>
        current.map((row) => (row.id === updated.id ? updated : row)),
      );

      setSummary(await getClaimSummary(runId!));
    } catch (caught) {
      setError((caught as Error)?.message ?? "Could not save the label.");
    } finally {
      setSaving(null);
    }
  };

  if (!run) {
    return (
      <EmptyState
        title="No run selected"
        detail="Pick a run to validate the claims its answers made."
      />
    );
  }

  return (
    <>
      {/* No <h1> here: the shell already renders the view's title, as it
          does for every other screen. */}
      <p className="ev-lede">
        Label the claims yourself. Agreement compares your verdicts with the
        evaluator's — the number to read first is false negatives, the
        unsupported claims it let through.
      </p>

      {summary && summary.validated_claims > 0 && (
        <div className="cl-agree">
          <Figure label="Validated" value={`${summary.validated_claims}`} />
          <Figure label="Agreement" value={pct(summary.agreement)} />
          <Figure label="Precision" value={pct(summary.precision)} />
          <Figure label="Recall" value={pct(summary.recall)} />
          <Figure label="F1" value={summary.f1.toFixed(2)} />
          <Figure label="False positives" value={`${summary.false_positives}`} />
          <Figure
            label="False negatives"
            value={`${summary.false_negatives}`}
            tone="bad"
          />
        </div>
      )}

      <Panel
        title="Claims"
        icon={ShieldCheck}
        span={12}
        note={
          summary
            ? `${summary.total_claims} claims · ${summary.validated_claims} validated`
            : undefined
        }
      >
        {error && <EmptyState title="Could not load claims" detail={error} />}

        {!error && (
          <div className="ev-tablewrap">
            <table className="ev-table cl-table">
              <thead>
                <tr>
                  <th scope="col">Claim</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Evaluator</th>
                  <th scope="col">Your label</th>
                  <th scope="col">Match</th>
                </tr>
              </thead>

              <tbody>
                {!rows.length && (
                  <tr>
                    <td className="cl-waiting" colSpan={5}>
                      {status === "loading"
                        ? `Reading the claims for ${shortRunId(run.run_id)}.`
                        : `Run ${shortRunId(run.run_id)} has no claims. Runs from before claim auditing existed show nothing here.`}
                    </td>
                  </tr>
                )}

                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span className="cl-claim">{row.claim}</span>

                      {row.is_numeric && (
                        <span
                          className="cl-numeric"
                          title="Numeric claims are held to the strict rule: the figure must appear in the evidence, or the arithmetic that produces it must."
                        >
                          numeric
                        </span>
                      )}

                      <span className="cl-meta">
                        {row.question_id}
                        {row.route ? ` · ${row.route}` : ""}
                      </span>
                    </td>

                    <td>
                      <details className="cl-ev">
                        <summary>{row.evidence.length} items</summary>
                        <ul>
                          {row.evidence.map((item, index) => (
                            <li key={index}>{item}</li>
                          ))}
                        </ul>
                      </details>
                    </td>

                    <td>
                      <LabelPill label={row.evaluator_label} />
                      {row.evaluator_reasoning && (
                        <span className="cl-reason">
                          {row.evaluator_reasoning}
                        </span>
                      )}
                    </td>

                    <td>
                      <div className="cl-choose">
                        {LABELS.map((option) => (
                          <button
                            key={option}
                            type="button"
                            className={`cl-btn${
                              row.human_label === option ? " cl-btn--on" : ""
                            }`}
                            disabled={saving === row.id}
                            onClick={() => label(row.id, option)}
                          >
                            {SHORT[option]}
                          </button>
                        ))}
                      </div>
                    </td>

                    <td className="ev-table__num">
                      {row.human_label
                        ? row.human_label === row.evaluator_label
                          ? "✓"
                          : "✗"
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bad";
}) {
  return (
    <div className="cl-figure">
      <span className="cl-figure__label">{label}</span>
      <span className={`cl-figure__value${tone ? ` cl-figure__value--${tone}` : ""}`}>
        {value}
      </span>
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
