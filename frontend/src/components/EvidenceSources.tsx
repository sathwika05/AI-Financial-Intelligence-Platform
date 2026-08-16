import { Check, Minus } from "lucide-react";
import type { SourcesUsed } from "../api/types";
import { sourceLabel } from "../lib/labels";
import "./EvidenceSources.css";

/** Fixed display order; any additional keys returned are appended. */
const KNOWN_SOURCES = ["sql", "vector", "market", "company_level_evidence"];

/**
 * System provenance: which retrieval channels this answer actually drew on.
 *
 * `details` carries counts derived from the response itself. Nothing is
 * inferred or estimated — a channel with no countable evidence in the payload
 * simply shows Used/Not used.
 */
export function EvidenceSources({
  sources,
  details,
}: {
  sources: SourcesUsed | null | undefined;
  details?: Record<string, string>;
}) {
  if (!sources) {
    return null;
  }

  const keys = [
    ...KNOWN_SOURCES.filter((key) => key in sources),
    ...Object.keys(sources).filter((key) => !KNOWN_SOURCES.includes(key)),
  ];

  if (keys.length === 0) {
    return null;
  }

  return (
    <ul className="sources">
      {keys.map((key) => {
        const used = sources[key] === true;
        const detail = used ? details?.[key] : undefined;

        return (
          <li
            key={key}
            className={`sources__item${used ? " sources__item--used" : ""}`}
          >
            <span className="sources__mark" aria-hidden="true">
              {used ? <Check size={11} /> : <Minus size={11} />}
            </span>
            <span className="sources__label">{sourceLabel(key)}</span>
            <span className="sources__state">
              {detail ?? (used ? "Used" : "Not used")}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
