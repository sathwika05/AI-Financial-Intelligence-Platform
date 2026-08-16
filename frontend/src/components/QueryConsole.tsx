import { useId } from "react";
import { QUERY_MAX_LENGTH, QUERY_MIN_LENGTH } from "../api/client";
import "./QueryConsole.css";

/**
 * Starting points only. These populate the input and never carry results.
 */
const SUGGESTIONS = [
  "Which technology companies combine attractive valuation with strong revenue growth?",
  "Rank companies with the strongest revenue and EPS growth",
  "Which semiconductor companies have the most positive sentiment in recent earnings reports?",
  "Find undervalued companies with low P/E ratios and positive earnings",
];

export function QueryConsole({
  value,
  onChange,
  onSubmit,
  isRunning,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isRunning: boolean;
}) {
  const inputId = useId();
  const trimmed = value.trim();
  const canSubmit = trimmed.length >= QUERY_MIN_LENGTH && !isRunning;

  return (
    <section className="console panel">
      <form
        className="console__form"
        onSubmit={(event) => {
          event.preventDefault();

          if (canSubmit) {
            onSubmit();
          }
        }}
      >
        <label className="eyebrow console__label" htmlFor={inputId}>
          Research question
        </label>

        <textarea
          id={inputId}
          className="console__input"
          value={value}
          rows={3}
          maxLength={QUERY_MAX_LENGTH}
          placeholder="Ask about company valuation, growth, fundamentals, or market sentiment..."
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();

              if (canSubmit) {
                onSubmit();
              }
            }
          }}
          disabled={isRunning}
        />

        <div className="console__foot">
          <span className="console__count num">
            {trimmed.length}/{QUERY_MAX_LENGTH}
          </span>

          <button type="submit" className="btn btn--primary" disabled={!canSubmit}>
            {isRunning ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </form>

      <div className="console__suggestions">
        <span className="eyebrow">Try</span>
        <ul className="console__chips">
          {SUGGESTIONS.map((suggestion) => (
            <li key={suggestion}>
              <button
                type="button"
                className="console__chip"
                onClick={() => onChange(suggestion)}
                disabled={isRunning}
              >
                {suggestion}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
