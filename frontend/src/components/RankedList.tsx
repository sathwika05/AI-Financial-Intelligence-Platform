import { useCallback, useState } from "react";
import type { RankedCompany } from "../api/types";
import type { CompanyEntry } from "../lib/entries";
import { CompanyRow } from "./CompanyRow";
import { ComparisonTable } from "./ComparisonTable";
import "./RankedList.css";

type View = "ranked" | "compare";

export interface RankedListProps {
  entries: CompanyEntry[];
  /** Scored candidates, which may include companies the analysis omitted. */
  comparisonCompanies: RankedCompany[];
}

/**
 * The single ranking for a question.
 *
 * One list, two ways to read it: expandable rows for reading a company, and a
 * column view for comparing them. Only one is on screen at a time, so the same
 * ranking is never rendered twice.
 */
export function RankedList({ entries, comparisonCompanies }: RankedListProps) {
  const [view, setView] = useState<View>("ranked");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [highlightCitation, setHighlightCitation] = useState<string | null>(
    null,
  );

  const toggle = useCallback((key: string) => {
    setHighlightCitation(null);
    setOpenKey((current) => (current === key ? null : key));
  }, []);

  // Compare view sends the reader back to the row it belongs to.
  const openFromComparison = useCallback(
    (company: RankedCompany) => {
      const ticker = company.ticker?.trim().toUpperCase();
      const name = company.name?.trim().toLowerCase();

      const match = entries.find((entry) => {
        const entryTicker = (
          entry.report?.ticker ?? entry.ranked?.ticker
        )?.trim().toUpperCase();
        const entryName = (entry.report?.name ?? entry.ranked?.name)
          ?.trim()
          .toLowerCase();

        return (
          (ticker && entryTicker === ticker) || (name && entryName === name)
        );
      });

      if (!match) {
        return;
      }

      setView("ranked");
      setHighlightCitation(null);
      setOpenKey(match.key);
    },
    [entries],
  );

  const extraCandidates = comparisonCompanies.length - entries.length;

  return (
    <section className="ranked panel">
      <header className="ranked__head">
        <div>
          <h2 className="block-title">Ranked companies</h2>
          <p className="ranked__note">
            {view === "ranked"
              ? "Ordered as returned for this question. Open a company to see why it ranked there."
              : extraCandidates > 0
                ? `All ${comparisonCompanies.length} scored candidates, including ${extraCandidates} not covered in the written analysis.`
                : "Every scored candidate, side by side."}
          </p>
        </div>

        <div className="ranked__views" role="group" aria-label="Result view">
          <button
            type="button"
            className={`ranked__view${view === "ranked" ? " ranked__view--active" : ""}`}
            onClick={() => setView("ranked")}
            aria-pressed={view === "ranked"}
          >
            Ranking
          </button>
          <button
            type="button"
            className={`ranked__view${view === "compare" ? " ranked__view--active" : ""}`}
            onClick={() => setView("compare")}
            aria-pressed={view === "compare"}
            disabled={comparisonCompanies.length === 0}
          >
            Compare
          </button>
        </div>
      </header>

      {view === "ranked" ? (
        <div className="ranked__rows">
          {entries.map((entry, index) => (
            <CompanyRow
              key={entry.key}
              entry={entry}
              index={index}
              expanded={openKey === entry.key}
              onToggle={() => toggle(entry.key)}
              highlightCitation={
                openKey === entry.key ? highlightCitation : null
              }
              onSelectCitation={(citationId) => {
                setOpenKey(entry.key);
                setHighlightCitation(citationId);
              }}
            />
          ))}
        </div>
      ) : (
        <ComparisonTable
          companies={comparisonCompanies}
          onOpenDetails={openFromComparison}
        />
      )}
    </section>
  );
}
