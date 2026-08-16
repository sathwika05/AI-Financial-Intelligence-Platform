import type { RankedCompany, ReportCompany } from "../api/types";

/**
 * Find the ranked-company record that corresponds to a reported company.
 *
 * The two lists can differ in length and membership (a SENTIMENT query
 * returned 1 reported company against 5 ranked ones), so this may legitimately
 * return undefined and callers must handle that.
 */
export function findRankedCompany(
  company: ReportCompany,
  ranked: RankedCompany[],
): RankedCompany | undefined {
  const ticker = company.ticker?.trim().toUpperCase();

  if (ticker) {
    const byTicker = ranked.find(
      (item) => item.ticker?.trim().toUpperCase() === ticker,
    );

    if (byTicker) {
      return byTicker;
    }
  }

  const name = company.name?.trim().toLowerCase();

  if (name) {
    return ranked.find((item) => item.name?.trim().toLowerCase() === name);
  }

  return undefined;
}

/** Stable React key for a company row or card. */
export function companyKey(
  company: { ticker?: string | null; name?: string | null; rank?: number | null },
  index: number,
): string {
  return (
    company.ticker?.trim() ||
    company.name?.trim() ||
    `company-${company.rank ?? index}`
  );
}
