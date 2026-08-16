import { useEffect, useState } from "react";
import "./States.css";

/**
 * Explanatory stages, not backend telemetry.
 *
 * The endpoint returns a single response with no progress stream, so these
 * describe what an analysis involves and advance on a timer. Nothing here
 * claims that a particular stage has finished.
 */
const STAGES = [
  "Understanding your question",
  "Analyzing financial data",
  "Reviewing evidence",
  "Ranking companies",
  "Preparing analysis",
];

export function LoadingState() {
  const [active, setActive] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActive((current) => (current + 1) % STAGES.length);
    }, 2600);

    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="state panel" aria-live="polite" aria-busy="true">
      <div className="state__pulse" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>

      <h2 className="state__title">Analyzing companies and financial evidence…</h2>

      <ul className="state__stages">
        {STAGES.map((stage, index) => (
          <li
            key={stage}
            className={`state__stage${
              index === active ? " state__stage--active" : ""
            }`}
          >
            {stage}
          </li>
        ))}
      </ul>

      <p className="state__caption">
        A full analysis runs several models over financial data and documents,
        and usually takes about a minute.
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
      <span className="eyebrow state__eyebrow">Analysis failed</span>
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
      <span className="eyebrow state__eyebrow">No companies returned</span>
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
