import type { SourcesUsed } from "../api/types";
import { sourceLabel } from "../lib/labels";
import "./EvidenceSources.css";

/** Fixed display order; any additional keys returned are appended. */
const KNOWN_SOURCES = ["sql", "vector", "market", "company_level_evidence"];

export function EvidenceSources({
  sources,
}: {
  sources: SourcesUsed | null | undefined;
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

        return (
          <li
            key={key}
            className={`sources__item${used ? " sources__item--used" : ""}`}
          >
            <span className="sources__mark" aria-hidden="true">
              {used ? "✓" : "—"}
            </span>
            <span className="sources__label">{sourceLabel(key)}</span>
            <span className="sources__state">{used ? "Used" : "Not used"}</span>
          </li>
        );
      })}
    </ul>
  );
}
