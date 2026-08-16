import { readFlag } from "../lib/labels";
import "./Warnings.css";

/**
 * Evidence limitations reported by the backend.
 *
 * Deliberately restrained: these are caveats on an analysis, not failures,
 * so they read as annotations rather than alarms. The original backend code
 * stays available in the title attribute.
 */
export function Warnings({
  flags,
  compact = false,
}: {
  flags: string[] | null | undefined;
  compact?: boolean;
}) {
  const items = (flags ?? []).filter((flag) => flag && flag.trim() !== "");

  if (items.length === 0) {
    return null;
  }

  return (
    <ul className={`warnings${compact ? " warnings--compact" : ""}`}>
      {items.map((flag, index) => {
        const readable = readFlag(flag);

        return (
          <li
            className="warnings__item"
            key={`${readable.raw}-${index}`}
            title={readable.raw}
          >
            <span className="warnings__mark" aria-hidden="true" />
            <span className="warnings__text">{readable.label}</span>
          </li>
        );
      })}
    </ul>
  );
}
