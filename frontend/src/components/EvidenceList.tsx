import type { DetailedEvidence, SummaryEvidence } from "../api/types";
import { formatScore } from "../lib/format";
import { sourceLabel } from "../lib/labels";
import "./EvidenceList.css";

/**
 * Anchor id for a citation. The same citation can appear in both evidence
 * sections, so each section namespaces its ids to keep them unique.
 */
export function evidenceAnchorId(
  scope: "claim" | "source",
  citationId: string,
): string {
  return `evidence-${scope}-${citationId}`;
}

/** Claims cited in the analysis itself: the simplest user-facing evidence. */
export function CitedClaims({
  evidence,
  highlightId,
}: {
  evidence: SummaryEvidence[] | null | undefined;
  highlightId?: string | null;
}) {
  const items = (evidence ?? []).filter((item) => item.claim || item.citation_id);

  if (items.length === 0) {
    return (
      <p className="evidence__empty">
        No cited claims were returned for this company.
      </p>
    );
  }

  return (
    <ul className="evidence">
      {items.map((item, index) => (
        <li
          key={item.citation_id ?? index}
          id={
            item.citation_id
              ? evidenceAnchorId("claim", item.citation_id)
              : undefined
          }
          className={`evidence__item${
            item.citation_id && item.citation_id === highlightId
              ? " evidence__item--highlight"
              : ""
          }`}
        >
          {item.claim && <p className="evidence__claim">{item.claim}</p>}
          {item.citation_id && (
            <span className="evidence__id num">{item.citation_id}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function groupBySource(
  evidence: DetailedEvidence[],
): Array<{ source: string; items: DetailedEvidence[] }> {
  const groups = new Map<string, DetailedEvidence[]>();

  for (const item of evidence) {
    const key = (item.source ?? "other").trim().toLowerCase();
    const bucket = groups.get(key);

    if (bucket) {
      bucket.push(item);
    } else {
      groups.set(key, [item]);
    }
  }

  return [...groups.entries()].map(([source, items]) => ({ source, items }));
}

/**
 * Detailed retrieval evidence, grouped by source and collapsed by default.
 *
 * Grouping keeps overlapping financial facts (the same figures arriving from
 * both the metrics and structured-data sources) out of the primary reading
 * path without altering what the backend returned.
 */
export function DetailedEvidenceGroups({
  evidence,
  highlightId,
}: {
  evidence: DetailedEvidence[] | null | undefined;
  highlightId?: string | null;
}) {
  const items = evidence ?? [];

  if (items.length === 0) {
    return (
      <p className="evidence__empty">
        No detailed source evidence was returned for this company.
      </p>
    );
  }

  const groups = groupBySource(items);

  return (
    <div className="evidence-groups">
      {groups.map(({ source, items: groupItems }) => {
        const containsHighlight = groupItems.some(
          (item) => item.citation_id && item.citation_id === highlightId,
        );

        return (
          <details
            key={source}
            className="evidence-group"
            open={containsHighlight}
          >
            <summary className="evidence-group__summary">
              <span className="evidence-group__label" title={`source: ${source}`}>
                {sourceLabel(source)}
              </span>
              <span className="evidence-group__count num">
                {groupItems.length}
              </span>
            </summary>

            <ul className="evidence">
              {groupItems.map((item, index) => (
                <li
                  key={item.citation_id ?? `${source}-${index}`}
                  id={
                    item.citation_id
                      ? evidenceAnchorId("source", item.citation_id)
                      : undefined
                  }
                  className={`evidence__item${
                    item.citation_id && item.citation_id === highlightId
                      ? " evidence__item--highlight"
                      : ""
                  }`}
                >
                  {item.text && <p className="evidence__text">{item.text}</p>}

                  <div className="evidence__meta">
                    {item.citation_id && (
                      <span className="evidence__id num">
                        {item.citation_id}
                      </span>
                    )}
                    {item.supports && (
                      <span className="evidence__supports">
                        supports {item.supports}
                      </span>
                    )}
                    {typeof item.rerank_score === "number" && (
                      <span className="evidence__score num">
                        relevance {formatScore(item.rerank_score)}
                      </span>
                    )}
                  </div>

                  {item.reason && (
                    <p className="evidence__reason">{item.reason}</p>
                  )}
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}
