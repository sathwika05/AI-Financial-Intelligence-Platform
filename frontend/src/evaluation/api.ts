/**
 * Evaluation API surface.
 *
 * Mirrors exactly what the backend exposes today — no more. Every panel on
 * the dashboard is built from these four shapes, and anything the endpoints
 * do not return is left off the screen rather than approximated.
 */

/** Mirrors `MetricsResponse` in backend/api/evaluation_routes.py. */
export interface RunMetrics {
  run_id: string;

  provider_id: string | null;
  provider_name: string | null;

  dataset: string;
  model: string;
  retrieval_mode: string;
  question_set: string;

  status: string;
  total_requests: number;
  total_cost: number;

  pass_rate: number | null;
  route_accuracy: number | null;

  precision_at_k: number | null;
  recall_at_k: number | null;
  mrr: number | null;
  ndcg_at_k: number | null;

  faithfulness: number | null;
  response_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  context_entity_recall: number | null;
  noise_sensitivity: number | null;

  hallucination_rate: number | null;
  intent_accuracy: number | null;

  /** Question counts per actual execution route, e.g. {"SQL Only": 7}.
   *  Null on runs recorded before the backend persisted it. */
  route_distribution: Record<string, number> | null;

  /** Metric averages per route, keyed by the same route names. Each block
   *  carries `count`, `pass_rate` and every canonical metric that had a
   *  value for that route. */
  route_performance: Record<
    string,
    Record<string, number | null | undefined>
  > | null;

  /** Invocation counts per tool name: calls, expected, hits, recall,
   *  precision. Null on runs recorded before it was persisted. */
  tool_summary: Record<
    string,
    Record<string, number | null | undefined>
  > | null;

  /** Mean latency and execution count per graph node. Null on runs recorded
   *  before the graph was instrumented. */
  node_latency: Record<
    string,
    Record<string, number | null | undefined>
  > | null;

  sql_accuracy: number | null;
  sql_equivalence: number | null;

  tool_accuracy: number | null;
  tool_precision: number | null;
  tool_recall: number | null;
  tool_f1: number | null;

  market_accuracy: number | null;

  avg_latency_ms: number | null;
  p50_latency: number | null;
  p95_latency: number | null;
  p99_latency: number | null;

  cost_per_request: number | null;
  /** Measured LLM tokens across the run. Null on runs recorded before
   *  usage tracking existed. */
  total_tokens: number | null;
  k: number | null;

  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

/** Mirrors `serialize_provider` in backend/api/admin_llm_routes.py. */
/** One question's result within a run.
 *
 * Persisted per question as the run goes, so a run that dies keeps what it
 * already scored — see the incremental write in evaluation_routes.
 */
export interface QuestionResult {
  question_id: string;
  question: string;
  expected_intent: string | null;
  actual_intent: string | null;
  overall_score: number | null;
  passed: boolean | null;
  aggregate_metrics: Record<string, number | null> | null;
  error: string | null;
}

export interface Provider {
  id: string;
  name: string;
  display_name: string;
  is_enabled: boolean;
  is_default: boolean;
  connection_status: string | null;
  last_tested_at: string | null;
  has_api_key: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** The `llm_models` row, serialized straight off the ORM. */
export interface ProviderModel {
  id: string;
  provider_id: string;
  tier: string;
  model_name: string;
  display_name: string | null;
  input_cost_per_million: string | number;
  output_cost_per_million: string | number;
  is_enabled: boolean;
}

/** Mirrors `RunRequest`. `model` is deliberately absent — the backend
 *  resolves the provider's small/medium/large tiers itself. */
export interface RunRequest {
  provider_id: string;
  dataset: string;
  retrieval_mode: string;
  question_set: QuestionSet;
  company_filter: string;
  top_k: number;
}

/** Mirrors `RunResponse` from the 202 returned by POST /run. */
export interface RunAccepted {
  run_id: string;
  status: string;
  provider_name: string;
  models: Record<string, string>;
  message: string;
}

/** The backend validates this as a `Literal`, so the UI cannot offer others. */
export const QUESTION_SETS = [
  "valuation",
  "growth",
  "sentiment",
  "mixed",
  "all",
] as const;

export type QuestionSet = (typeof QUESTION_SETS)[number];

/** Free-form on the backend; these are the strategies the graph implements. */
export const RETRIEVAL_MODES = [
  "hybrid+reranker",
  "hybrid",
  "vector",
  "sql",
] as const;

export const DATASETS = ["SEC Filings", "Earnings Calls", "News"] as const;

export class EvaluationApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "EvaluationApiError";
    this.status = status;
  }
}

/** FastAPI reports errors as `detail`, either a string or a 422 issue list. */
async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();

    if (!body || typeof body !== "object" || !("detail" in body)) {
      return null;
    }

    const detail = (body as { detail: unknown }).detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : null,
        )
        .filter((message): message is string => Boolean(message));

      return messages.length > 0 ? messages.join("; ") : null;
    }

    return null;
  } catch {
    return null;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;

  try {
    response = await fetch(path, { ...init, signal });
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw caught;
    }

    throw new EvaluationApiError(
      "Could not reach the evaluation service. Is the backend running?",
    );
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);

    throw new EvaluationApiError(
      detail ?? `Request failed with status ${response.status}.`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

export function listRuns(
  limit = 50,
  signal?: AbortSignal,
): Promise<RunMetrics[]> {
  return request<RunMetrics[]>(
    `/api/evaluation/runs?limit=${limit}&offset=0`,
    {},
    signal,
  );
}

export function getRun(
  runId: string,
  signal?: AbortSignal,
): Promise<RunMetrics> {
  return request<RunMetrics>(`/api/evaluation/runs/${runId}`, {}, signal);
}

export function getRunQuestions(
  runId: string,
  signal?: AbortSignal,
): Promise<QuestionResult[]> {
  return request<QuestionResult[]>(
    `/api/evaluation/runs/${runId}/questions`,
    {},
    signal,
  );
}

export function triggerRun(
  payload: RunRequest,
  signal?: AbortSignal,
): Promise<RunAccepted> {
  return request<RunAccepted>(
    "/api/evaluation/run",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    signal,
  );
}

export function listProviders(signal?: AbortSignal): Promise<Provider[]> {
  return request<Provider[]>("/admin/llm/providers", {}, signal);
}

export function listProviderModels(
  providerId: string,
  signal?: AbortSignal,
): Promise<ProviderModel[]> {
  return request<ProviderModel[]>(
    `/admin/llm/providers/${providerId}/models`,
    {},
    signal,
  );
}
