import type { RankedCompany, ReportCompany } from "../api/types";
import { companyKey, findRankedCompany } from "./companies";

/**
 * One company as the interface needs it: the written analysis record and the
 * scored record, paired where both exist.
 *
 * The two API lists can differ in length and membership, so either half may
 * be missing and every consumer must tolerate that.
 */
export interface CompanyEntry {
  key: string;
  report?: ReportCompany;
  ranked?: RankedCompany;
}

/**
 * Build the primary ranking.
 *
 * The written analysis (`final_report.top_companies`) drives the list and its
 * order. When the analysis reported nothing, the scored candidates stand in so
 * the user still sees the ranking rather than an empty screen.
 */
export function buildEntries(
  reportCompanies: ReportCompany[],
  rankedCompanies: RankedCompany[],
): CompanyEntry[] {
  if (reportCompanies.length > 0) {
    return reportCompanies.map((report, index) => ({
      key: companyKey(report, index),
      report,
      ranked: findRankedCompany(report, rankedCompanies),
    }));
  }

  return rankedCompanies.map((ranked, index) => ({
    key: companyKey(ranked, index),
    ranked,
  }));
}

/** Fields read from whichever half of the pair carries them. */
export function entryFacts(entry: CompanyEntry) {
  const { report, ranked } = entry;

  return {
    rank: report?.rank ?? ranked?.rank ?? null,
    ticker: report?.ticker?.trim() || ranked?.ticker?.trim() || null,
    name: report?.name?.trim() || ranked?.name?.trim() || "Unknown company",
    finalScore: report?.final_score ?? ranked?.final_score ?? null,
    confidence: report?.confidence ?? null,
    recommendation: report?.recommendation ?? null,
    metrics: report?.key_metrics ?? ranked?.metrics ?? null,
    flags: report?.flags ?? null,
    summary: report?.summary ?? null,
    sector: ranked?.sector ?? null,
  };
}

/** Citation ids this company can resolve, used to detect citation markers. */
export function entryCitationIds(entry: CompanyEntry): Set<string> {
  const ids = new Set<string>();

  for (const item of entry.report?.evidence ?? []) {
    if (item.citation_id) {
      ids.add(item.citation_id);
    }
  }

  for (const item of entry.ranked?.evidence ?? []) {
    if (item.citation_id) {
      ids.add(item.citation_id);
    }
  }

  return ids;
}
