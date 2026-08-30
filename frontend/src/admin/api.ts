import { withAuth } from "../auth/session";
import type { Provider } from "../evaluation/api";

/**
 * Admin mutations.
 *
 * The endpoints have existed since the provider registry was built; only
 * the read path was ever wired to a screen, so a provider could be listed
 * but not changed without curl.
 */

export class AdminApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
  }
}

async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;

  try {
    response = await fetch(path, withAuth(init));
  } catch {
    throw new AdminApiError("Could not reach the server.");
  }

  if (response.status === 403) {
    throw new AdminApiError(
      "That action needs the admin role.",
      403,
    );
  }

  if (!response.ok) {
    let detail: string | null = null;

    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : null;
    } catch {
      detail = null;
    }

    throw new AdminApiError(
      detail ?? `Request failed with status ${response.status}.`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

export function listProviders(): Promise<Provider[]> {
  return send<Provider[]>("/admin/llm/providers");
}

/** Enable or disable. Disabling also clears default, server-side. */
export interface ProviderModel {
  id: string;
  provider_id: string;
  model_name: string;
  display_name: string;
  tier: string;
  is_enabled: boolean;
  input_cost_per_million: number | null;
  output_cost_per_million: number | null;
}

/** The small/medium/large tiers a provider resolves to. */
export function listProviderModels(id: string): Promise<ProviderModel[]> {
  return send<ProviderModel[]>(`/admin/llm/providers/${id}/models`);
}

export function toggleProvider(id: string): Promise<Provider> {
  return send<Provider>(`/admin/llm/providers/${id}/toggle`, {
    method: "POST",
  });
}

/** Exactly one provider is default; the server clears the others. */
export function setDefaultProvider(id: string): Promise<Provider> {
  return send<Provider>(`/admin/llm/providers/${id}/set-default`, {
    method: "POST",
  });
}

export interface IndexRequest {
  document_id?: number;
}

export interface IndexAccepted {
  message: string;
}

/**
 * Trigger chunk -> embed -> store for one document, or the whole backlog.
 *
 * Returns as soon as the work is queued. The endpoint runs it as a
 * background task with no job record, so a failure after this point --
 * document missing, no chunks produced, embedding API down -- reaches the
 * server log and nothing else.
 */
export function startIndexing(request: IndexRequest): Promise<IndexAccepted> {
  return send<IndexAccepted>("/api/index/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/* ── Ingestion ──────────────────────────────────────────────
 *
 * Two of these three work with no AWS configured, which is the point:
 * the S3 path cannot be exercised locally, but what EDGAR returns and
 * whether Docling can read a given file both can.
 */

export interface EdgarFiling {
  accession: string;
  form: string;
  filing_date: string;
  document: string;
  url: string;
  cik: string;
  ticker: string | null;
}

export interface StoredDocument {
  id: number;
  title: string | null;
  doc_type: string | null;
  source: string | null;
  status: string;
  ticker: string | null;
  chunks: number;
  created_at: string | null;
}

export interface UploadAccepted {
  document_id: number;
  title: string | null;
  characters: number;
  status: string;
  message: string;
}

export function previewFilings(
  ticker: string,
  forms: string,
  limit: number,
): Promise<{ ticker: string; filings: EdgarFiling[] }> {
  const query = new URLSearchParams({
    ticker,
    forms,
    limit: String(limit),
  });

  return send(`/api/ingestion/edgar/filings?${query}`);
}

export function listDocuments(
  limit = 25,
): Promise<{ total: number; documents: StoredDocument[] }> {
  return send(`/api/ingestion/documents?limit=${limit}`);
}

export function uploadDocument(
  file: File,
  ticker: string,
): Promise<UploadAccepted> {
  const form = new FormData();

  form.append("file", file);

  if (ticker.trim()) {
    form.append("ticker", ticker.trim());
  }

  // No Content-Type header: the browser sets it, and it has to include
  // the multipart boundary it generated. Setting it by hand produces a
  // body the server cannot parse.
  return send("/api/ingestion/documents", { method: "POST", body: form });
}

/* ── External observability links ───────────────────────────
 *
 * CloudWatch and LangSmith are external products with better interfaces
 * than anything worth rebuilding here, so the rail links out rather than
 * proxying them. The URLs differ per deployment, so they come from the
 * server rather than being baked into the bundle at build time — one
 * image, many deployments.
 */

export interface ExternalLink {
  configured: boolean;
  url: string | null;
  detail: string | null;
}

export interface ExternalLinks {
  cloudwatch: ExternalLink;
  langsmith: ExternalLink;
}

export function fetchExternalLinks(): Promise<ExternalLinks> {
  return send<ExternalLinks>("/api/admin/external-links");
}

export interface IndexFilingRequest {
  cik: string;
  accession: string;
  form: string;
  filing_date: string;
  primary_document: string;
  ticker: string | null;
}

/**
 * Download one EDGAR filing and index it, with no bucket in the path.
 *
 * The fields go up, never the URL: the server rebuilds it and checks the
 * host, so this cannot be pointed somewhere else.
 */
export function indexFiling(
  filing: IndexFilingRequest,
): Promise<UploadAccepted> {
  return send<UploadAccepted>("/api/ingestion/edgar/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filing),
  });
}

export interface JobAccepted {
  message: string;
}

/** Index recent filings for several companies. Additive and repeatable. */
export function collectFilings(
  tickers: string[],
  forms: string[],
  limit: number,
): Promise<JobAccepted> {
  return send<JobAccepted>("/api/ingestion/edgar/collect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tickers, forms, limit }),
  });
}

/**
 * Rebuild the corpus from Alpha Vantage and Finnhub.
 *
 * Destructive: the tables are emptied and refilled with data fetched now.
 * The server refuses without the exact phrase, which is the point — this
 * must not be reachable by one stray click.
 */
export const RESEED_CONFIRMATION = "replace the corpus";

export function reseedCorpus(confirm: string): Promise<JobAccepted> {
  return send<JobAccepted>("/api/ingestion/seed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm }),
  });
}

export interface KnownCompany {
  ticker: string;
  name: string;
}

/**
 * The companies whose filings can be fetched.
 *
 * Fifty, seeded from seeds/companies.csv. Anything else has no financial
 * metrics in the corpus, so a document fetched for it answers questions
 * the rest of the system cannot support.
 */
export function listCompanies(): Promise<{ companies: KnownCompany[] }> {
  return send<{ companies: KnownCompany[] }>("/api/ingestion/companies");
}

export interface IngestionEvent {
  id: number;
  source: string;
  reference: string;
  outcome: string;
  detail: string | null;
  document_id: number | null;
  chunks: number | null;
  at: string | null;
}

/**
 * What happened to each file that was attempted.
 *
 * Distinct from the document list, which can only show what was stored.
 * The interesting rows here are the ones with no document attached.
 */
export function listIngestionEvents(
  limit = 25,
  source?: string,
): Promise<{ events: IngestionEvent[] }> {
  const query = new URLSearchParams({ limit: String(limit) });

  if (source) query.set("source", source);

  return send<{ events: IngestionEvent[] }>(`/api/ingestion/events?${query}`);
}
