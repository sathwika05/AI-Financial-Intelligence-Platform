import { useId } from "react";
import { CornerDownLeft, Loader2, Sparkles } from "lucide-react";
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

/**
 * The research command surface.
 *
 * Compact by default: the field is three lines, the suggestions sit on one
 * row beneath it, and the only element carrying colour is the action the
 * reader is meant to take.
 */
export function QueryConsole({
  value,
  onChange,
  onSubmit,
  isRunning,
  compact = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isRunning: boolean;
  /** Once results exist they should own the viewport, so the console gives
   *  back the height it no longer needs. */
  compact?: boolean;
}) {
  const inputId = useId();
  const trimmed = value.trim();
  const canSubmit = trimmed.length >= QUERY_MIN_LENGTH && !isRunning;
  const nearLimit = trimmed.length > QUERY_MAX_LENGTH * 0.9;

  return (
    <section className={`console panel${compact ? " console--compact" : ""}`}>
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

        <div className="console__field">
          <textarea
            id={inputId}
            className="console__input"
            value={value}
            rows={compact ? 1 : 2}
            maxLength={QUERY_MAX_LENGTH}
            placeholder="Ask about company valuation, growth, fundamentals, or market sentiment…"
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

          <div className="console__actions">
            <span
              className={`console__count num${
                nearLimit ? " console__count--near" : ""
              }`}
            >
              {trimmed.length}/{QUERY_MAX_LENGTH}
            </span>

            <span className="console__hint">
              <CornerDownLeft size={11} aria-hidden="true" />
              &#8984; Enter
            </span>

            <button
              type="submit"
              className="btn btn--primary console__submit"
              disabled={!canSubmit}
            >
              {isRunning ? (
                <>
                  <Loader2 size={14} className="console__spin" aria-hidden="true" />
                  Analyzing…
                </>
              ) : (
                <>
                  <Sparkles size={14} aria-hidden="true" />
                  Analyze
                </>
              )}
            </button>
          </div>
        </div>
      </form>

      <div className="console__suggestions">
        <span className="eyebrow console__suggestions-label">Try</span>
        <ul className="console__chips">
          {SUGGESTIONS.map((suggestion) => (
            <li key={suggestion}>
              <button
                type="button"
                className="console__chip"
                onClick={() => onChange(suggestion)}
                disabled={isRunning}
                title={suggestion}
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
