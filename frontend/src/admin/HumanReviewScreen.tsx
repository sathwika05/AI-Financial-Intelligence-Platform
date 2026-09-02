import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, CircleSlash, ShieldAlert } from "lucide-react";
import {
  AdminApiError,
  listEscalations,
  resolveEscalation,
  type Escalation,
} from "./api";
import "./AdminScreens.css";
import "./HumanReview.css";

/**
 * The queue of answers the pipeline refused to show.
 *
 * When the reviewer scores its own report below the escalation threshold,
 * the ranking is withheld server-side and the analyst gets a sentence
 * instead. This is where the withheld ranking goes.
 *
 * The row leads with the draft rather than the metadata, because the only
 * question worth asking of an escalation is "was the system right to
 * withhold this?" — and that cannot be answered from a confidence number.
 * Everything else on the row exists to support that judgement: the flags
 * say what the reviewer objected to, the intent says which branch ran.
 *
 * Resolved and dismissed are kept apart deliberately. "Resolved" means an
 * admin read it and accepted the outcome; "dismissed" means the
 * escalation itself was noise. Collapsing them into "done" would make the
 * queue's own accuracy unmeasurable.
 */

type Filter = "pending" | "resolved" | "dismissed" | "all";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "pending", label: "Pending" },
  { id: "resolved", label: "Resolved" },
  { id: "dismissed", label: "Dismissed" },
  { id: "all", label: "All" },
];

export function HumanReviewScreen() {
  const [rows, setRows] = useState<Escalation[]>([]);
  const [filter, setFilter] = useState<Filter>("pending");
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");

    try {
      const page = await listEscalations(filter);

      setRows(page.escalations);
      setStatus("ready");
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not load the review queue.",
      );
      setStatus("error");
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(
    row: Escalation,
    decision: "resolved" | "dismissed",
  ) {
    setBusyId(row.id);

    try {
      await resolveEscalation(row.id, decision, notes[row.id] ?? "");
      await load();
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not record that decision.",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="screen">
      <header className="screen__head">
        <h1 className="screen__title">Human-in-the-Loop</h1>
        <p className="screen__lede">
          Answers the reviewer scored below its confidence floor. Each one was
          withheld from the analyst who asked and sent here instead, with the
          ranking they never saw.
        </p>
      </header>

      <div className="hr__filters" role="tablist" aria-label="Queue">
        {FILTERS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={filter === id}
            className={`hr__filter${filter === id ? " hr__filter--on" : ""}`}
            onClick={() => setFilter(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <p className="screen__error">{error}</p>}

      {status === "loading" && <p className="screen__note">Loading…</p>}

      {status === "ready" && rows.length === 0 && (
        <p className="screen__note">
          {filter === "pending"
            ? "Nothing is waiting for review. Every answer the pipeline has produced met its confidence floor."
            : "No escalations with that status."}
        </p>
      )}

      <div className="hr__list">
        {rows.map((row) => (
          <EscalationCard
            key={row.id}
            row={row}
            note={notes[row.id] ?? ""}
            busy={busyId === row.id}
            onNote={(text) =>
              setNotes((current) => ({ ...current, [row.id]: text }))
            }
            onDecide={(decision) => void decide(row, decision)}
          />
        ))}
      </div>
    </div>
  );
}

function EscalationCard({
  row,
  note,
  busy,
  onNote,
  onDecide,
}: {
  row: Escalation;
  note: string;
  busy: boolean;
  onNote: (text: string) => void;
  onDecide: (decision: "resolved" | "dismissed") => void;
}) {
  const companies = row.withheld_report?.companies ?? [];
  const open = row.status === "pending";

  return (
    <article className={`hr__card${open ? "" : " hr__card--closed"}`}>
      <header className="hr__card-head">
        <ShieldAlert size={15} className="hr__card-icon" aria-hidden="true" />

        <p className="hr__query">{row.query}</p>

        <span className="hr__score num" title="Overall confidence">
          {row.confidence.toFixed(2)}
        </span>
      </header>

      <p className="hr__meta">
        {[
          row.intent,
          row.created_at ? new Date(row.created_at).toLocaleString() : null,
          `#${row.id}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>

      {/* The reason the row exists: what the analyst would have been shown. */}
      {companies.length > 0 && (
        <div className="hr__withheld">
          <span className="eyebrow">Withheld ranking</span>
          <ol className="hr__ranking">
            {companies.map((company, index) => (
              <li key={`${company.ticker ?? index}`} className="hr__rank">
                <span className="hr__rank-pos num">{index + 1}</span>
                <span className="hr__rank-ticker">
                  {company.ticker ?? "—"}
                </span>
                {typeof company.confidence === "number" && (
                  <span className="hr__rank-score num">
                    {company.confidence.toFixed(2)}
                  </span>
                )}
                {company.rationale && (
                  <span className="hr__rank-why">{company.rationale}</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {row.review_flags.length > 0 && (
        <div className="hr__flags">
          <span className="eyebrow">What the reviewer objected to</span>
          <ul className="hr__flag-list">
            {row.review_flags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        </div>
      )}

      {open ? (
        <div className="hr__decide">
          <label className="hr__note-label" htmlFor={`note-${row.id}`}>
            Note (optional)
          </label>
          <textarea
            id={`note-${row.id}`}
            className="hr__note"
            rows={2}
            value={note}
            placeholder="Why this was or wasn't a real problem."
            onChange={(event) => onNote(event.target.value)}
          />

          <div className="hr__actions">
            <button
              type="button"
              className="screen__btn screen__btn--primary"
              disabled={busy}
              onClick={() => onDecide("resolved")}
            >
              <CheckCircle2 size={13} aria-hidden="true" /> Accept the withhold
            </button>

            <button
              type="button"
              className="screen__btn"
              disabled={busy}
              onClick={() => onDecide("dismissed")}
            >
              <CircleSlash size={13} aria-hidden="true" /> Dismiss as noise
            </button>
          </div>
        </div>
      ) : (
        <p className="hr__resolution">
          <span
            className={`screen__pill screen__pill--${
              row.status === "resolved" ? "ok" : "warn"
            }`}
          >
            {row.status}
          </span>
          {row.reviewed_by && <> by {row.reviewed_by}</>}
          {row.resolution_note && <> — “{row.resolution_note}”</>}
        </p>
      )}
    </article>
  );
}
