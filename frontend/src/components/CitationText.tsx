import { splitCitations } from "../lib/citations";
import "./CitationText.css";

/**
 * Render a summary with its citation markers as interactive tokens.
 *
 * Citation ids are internal identifiers, so they link to the matching
 * evidence inside company details rather than to a fabricated URL.
 */
export function CitationText({
  text,
  knownIds,
  onSelectCitation,
}: {
  text: string | null | undefined;
  knownIds: ReadonlySet<string>;
  onSelectCitation?: (citationId: string) => void;
}) {
  const segments = splitCitations(text, knownIds);

  if (segments.length === 0) {
    return null;
  }

  return (
    <p className="citation-text">
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <span key={index}>{segment.value}</span>
        ) : onSelectCitation ? (
          <button
            key={index}
            type="button"
            className="citation"
            onClick={() => onSelectCitation(segment.value)}
            title={`Show supporting evidence ${segment.value}`}
          >
            {segment.value}
          </button>
        ) : (
          <span key={index} className="citation citation--static">
            {segment.value}
          </span>
        ),
      )}
    </p>
  );
}
