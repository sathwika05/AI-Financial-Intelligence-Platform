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

/** Rows per page. Small enough to read carefully, which is the task. */
const PAGE_SIZE = 25;

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

  // Server-side, both of them: a hundred-question run is over a
  // thousand claims, and filtering in the browser would ship all of them
  // to hide most of them.
  const [verdict, setVerdict] = useState<"" | ClaimLabel>("");
  const [mine, setMine] = useState<"" | "labeled" | "unlabeled">("");

  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);

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
          getRunClaims(
            runId,
            {
              label: verdict || undefined,
              labeled: mine === "labeled",
              unlabeled: mine === "unlabeled",
              offset: page * PAGE_SIZE,
              limit: PAGE_SIZE,
            },
            signal,
          ),
          getClaimSummary(runId, signal),
        ]);

        setRows(claims.items);
        setTotal(claims.total);
        setSummary(totals);
        setError(null);
        setStatus("ready");
      } catch (caught) {
        if ((caught as Error)?.name === "AbortError") return;

        setError((caught as Error)?.message ?? "Could not load claims.");
        setStatus("error");
      }
    },
    [runId, verdict, mine, page],
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

      <div className="cl-filters">
        <label className="cl-filter">
          <span>Evaluator said</span>
          <select
            value={verdict}
            onChange={(event) => {
              setVerdict(event.target.value as "" | ClaimLabel);
              setPage(0);
            }}
          >
            <option value="">Anything</option>
            {LABELS.map((option) => (
              <option key={option} value={option}>{SHORT[option]}</option>
            ))}
          </select>
        </label>

        <label className="cl-filter">
          <span>Your label</span>
          <select
            value={mine}
            onChange={(event) => {
              setMine(event.target.value as "" | "labeled" | "unlabeled");
              setPage(0);
            }}
          >
            <option value="">Anything</option>
            <option value="unlabeled">Not labelled yet</option>
            <option value="labeled">Already labelled</option>
          </select>
        </label>

        <span className="cl-filters__count">
          {total === 0
            ? "nothing matches"
            : `${page * PAGE_SIZE + 1}\u2013${Math.min((page + 1) * PAGE_SIZE, total)} of ${total}`}
        </span>
      </div>

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
                      {/* The question first: a claim cannot be judged
                          without knowing what was asked. */}
                      {row.question && (
                        <span className="cl-question">{row.question}</span>
                      )}

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
                      {/* One select rather than three stacked buttons.
                          The buttons were three rows tall in a table whose
                          other cells are one, which is what let the
                          evaluator's reasoning overlap them. */}
                      <select
                        className="cl-select"
                        value={row.human_label ?? ""}
                        disabled={saving === row.id}
                        aria-label={`Your label for: ${row.claim}`}
                        onChange={(event) =>
                          event.target.value &&
                          label(row.id, event.target.value as ClaimLabel)
                        }
                      >
                        <option value="">Not labelled</option>
                        {LABELS.map((option) => (
                          <option key={option} value={option}>
                            {SHORT[option]}
                          </option>
                        ))}
                      </select>
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
        {total > PAGE_SIZE && (
          <nav className="cl-pager" aria-label="Claim pages">
            <button
              type="button"
              className="cl-page"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(current - 1, 0))}
            >
              Previous
            </button>

            <span className="cl-pager__at">
              Page {page + 1} of {Math.ceil(total / PAGE_SIZE)}
            </span>

            <button
              type="button"
              className="cl-page"
              disabled={(page + 1) * PAGE_SIZE >= total}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </nav>
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
