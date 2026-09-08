/**
 * Types for POST /api/retrieve/financial.
 *
 * Modelled against real responses from the running backend, which vary more
 * than the happy path suggests:
 *
 *  - `key_metrics.market_cap` has been observed as a number (5453358039040.0)
 *    AND as a numeric string ("800222937088").
 *  - `key_metrics.revenue_growth` arrives pre-formatted ("85.2%"), while
 *    `metrics.revenue_growth` on ranked companies is a decimal (0.852).
 *  - `final_report.top_companies` and `ranked_companies` can differ in both
 *    length and membership (a SENTIMENT query returned 1 vs 5).
 *  - `flags` arrive as SCREAMING_SNAKE codes in some runs and as plain
 *    sentences in others.
 *  - `weights_used` is dynamic per query and can contain 0.0 entries.
 *
 * Every field is therefore treated as optional and nullable.
 */

/** A financial figure that may be a number, a pre-formatted string, or absent. */
export type MetricValue = number | string | null;

export type FactorMap = Record<string, number | null | undefined>;

export interface KeyMetrics {
  pe_ratio?: MetricValue;
  revenue_growth?: MetricValue;
  eps?: MetricValue;
  market_cap?: MetricValue;
  [key: string]: MetricValue | undefined;
}

/** Evidence attached to the final report: claim + citation only. */
export interface SummaryEvidence {
  claim?: string | null;
  citation_id?: string | null;
}

/** Evidence attached to ranked companies; rerank_score/reason are optional. */
export interface DetailedEvidence {
  citation_id?: string | null;
  source?: string | null;
  text?: string | null;
  supports?: string | null;
  rerank_score?: number | null;
  reason?: string | null;
}

export interface ReportCompany {
  rank?: number | null;
  ticker?: string | null;
  name?: string | null;
  final_score?: number | null;
  recommendation?: string | null;
  summary?: string | null;
  key_metrics?: KeyMetrics | null;
  evidence?: SummaryEvidence[] | null;
  confidence?: number | null;
  flags?: string[] | null;
}

export interface SourcesUsed {
  sql?: boolean | null;
  vector?: boolean | null;
  market?: boolean | null;
  company_level_evidence?: boolean | null;
  [key: string]: boolean | null | undefined;
}

/**
 * Internal reviewer output. Mostly not surfaced in this experience --
 * `escalated` and `notice` are the exceptions, because a withheld answer
 * has to explain itself to the person who asked.
 */
export interface ReportReview {
  decision?: string | null;
  hallucination_rate?: number | null;
  total_flags?: number | null;
  flags?: string[] | null;
  escalated?: boolean | null;
  notice?: string | null;
}

export interface FinalReport {
  query_summary?: string | null;
  intent?: string | null;
  top_companies?: ReportCompany[] | null;
  /**
   * The server withheld the ranking. Distinct from an empty
   * `top_companies`, which also means "nothing matched" -- this says the
   * pipeline had an answer and declined to show it.
   */
  withheld?: boolean | null;
  /**
   * The classifier declined the question before anything ran. Distinct
   * from `withheld`: that one means the pipeline produced a result the
   * server would not stand behind, this one means there was nothing to
   * research. They need different words, so they need different flags.
   */
  out_of_scope?: boolean | null;
  overall_confidence?: number | null;
  evidence_quality?: string | null;
  review?: ReportReview | null;
  sources_used?: SourcesUsed | null;
}

export interface Explainability {
  final_score?: number | null;
  interpretation?: string | null;
  scores?: FactorMap | null;
  weights?: FactorMap | null;
  contributions?: FactorMap | null;
}

export interface RankedCompany {
  company_id?: number | string | null;
  name?: string | null;
  ticker?: string | null;
  sector?: string | null;
  final_score?: number | null;
  llm_score?: number | null;
  scores?: FactorMap | null;
  weights?: FactorMap | null;
  metrics?: KeyMetrics | null;
  rank?: number | null;
  evidence?: DetailedEvidence[] | null;
  evidence_count?: number | null;
  explainability?: Explainability | null;
  interpretation?: string | null;
}

export interface ScoringResult {
  weights_used?: FactorMap | null;
  intent?: string | null;
  /** Counts more candidates than the report shows; not displayed. */
  total_ranked?: number | null;
  /** Internal retrieval detail; not displayed. */
  reranked_context_count?: number | null;
}

export interface FinancialQueryResponse {
  query?: string | null;
  provider?: string | null;
  final_report?: FinalReport | null;
  ranked_companies?: RankedCompany[] | null;
  scoring_result?: ScoringResult | null;
}
