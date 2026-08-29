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
): Promise<{ documents: StoredDocument[] }> {
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
