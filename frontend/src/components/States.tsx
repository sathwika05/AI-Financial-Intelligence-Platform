import { useEffect, useState } from "react";
import { AlertCircle, Loader2, SearchX, ShieldAlert } from "lucide-react";
import "./States.css";

/**
 * The stages an analysis passes through.
 *
 * The endpoint returns a single response with no progress stream, so these
 * describe what the pipeline does — they are not telemetry. Nothing is marked
 * complete and no stage is advanced on a timer, because either would assert
 * progress the backend never reported. The only live figure here is elapsed
 * time, which is measured in the browser and is therefore real.
 */
const STAGES = [
  "Understanding the question",
  "Retrieving financial data",
  "Reviewing evidence",
  "Ranking companies",
  "Preparing analysis",
];

function useElapsedSeconds(): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );

    return () => window.clearInterval(timer);
  }, []);

  return seconds;
}

export function LoadingState() {
  const elapsed = useElapsedSeconds();

  return (
    <section className="state panel" aria-live="polite" aria-busy="true">
      <div className="state__head">
        <Loader2 size={15} className="state__spin" aria-hidden="true" />
        <h2 className="state__title">Running analysis</h2>
        <span className="state__elapsed num">
          {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
        </span>
      </div>

      <ol className="state__stages">
        {STAGES.map((stage) => (
          <li key={stage} className="state__stage">
            <span className="state__stage-mark" aria-hidden="true" />
            {stage}
          </li>
        ))}
      </ol>

      <p className="state__caption">
        The pipeline runs several models over financial data and documents and
        returns one result when every stage is done, so per-stage progress is
        not reported. A full analysis usually takes about a minute.
      </p>
    </section>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <section className="state state--error panel" role="alert">
      <div className="state__head">
        <AlertCircle size={15} className="state__icon-error" aria-hidden="true" />
        <span className="eyebrow state__eyebrow">Analysis failed</span>
      </div>

      <h2 className="state__title state__title--error">{message}</h2>

      <button type="button" className="btn btn--ghost" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}

export function NoResultsState() {
  return (
    <section className="state state--empty panel">
      <div className="state__head">
        <SearchX size={15} className="state__icon-empty" aria-hidden="true" />
        <span className="eyebrow state__eyebrow">No companies returned</span>
      </div>

      <h2 className="state__title state__title--empty">
        This question produced an analysis but no ranked companies.
      </h2>

      <p className="state__caption">
        Try naming a sector, a metric, or a comparison — for example
        &ldquo;technology companies with low P/E and strong revenue
        growth&rdquo;.
      </p>
    </section>
  );
}

/**
 * Shown in place of a ranking the system declined to stand behind.
 *
 * Not an error and not an empty result, and it must not read as either.
 * The pipeline ran, found companies, and ranked them — then scored its own
 * confidence below the floor, so the ranking was withheld on the server
 * and an administrator was sent the draft.
 *
 * The alternative was showing the ranking with a warning above it, which
 * assumes the warning is read. It is not: a table of tickers and scores
 * looks equally authoritative at 0.17 as at 0.91.
 */
export function WithheldState({
  notice,
  confidence,
}: {
  notice?: string | null;
  confidence?: number | null;
}) {
  return (
    <section className="state state--withheld panel" role="status">
      <div className="state__head">
        <ShieldAlert size={15} className="state__icon-withheld" aria-hidden="true" />
        <span className="eyebrow state__eyebrow">Answer withheld</span>
        {typeof confidence === "number" && (
          <span className="state__elapsed num">
            confidence {confidence.toFixed(2)}
          </span>
        )}
      </div>

      <h2 className="state__title state__title--withheld">
        {notice ??
          "This answer did not meet the confidence threshold, so it was " +
            "withheld and sent to an administrator for review."}
      </h2>

      <p className="state__caption">
        Nothing is wrong with your question. The evidence behind this one was
        too thin for the system to rank companies honestly — narrowing it to
        named companies, or to a sector the corpus covers, usually helps.
      </p>
    </section>
  );
}
