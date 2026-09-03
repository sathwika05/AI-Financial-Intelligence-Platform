import { onUnauthorized, withAuth } from "../auth/session";
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

  /** Which retrieval pipeline produced this run. */
  rrf_enabled: boolean;
  cross_encoder_enabled: boolean;

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

  /** Both off is the baseline pipeline. Independent of each other. */
  rrf_enabled: boolean;
  cross_encoder_enabled: boolean;
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

/**
 * pgvector index types, for the launcher's Index Type selector.
 *
 * Display only: the selection is not part of RunRequest and does not reach
 * the backend. The index in the database is IVFFlat with lists=100, created
 * in the d915f0965263 migration, whatever is chosen here.
 */
export const INDEX_TYPES = ["Flat", "IVFFlat", "HNSW"] as const;

/**
 * The retrieval pipeline, as one choice rather than two checkboxes.
 *
 * The backend takes two independent booleans, but only these four
 * combinations are meaningful to compare, and a single selector keeps the
 * launcher honest about that: you pick the arm you are benchmarking, not two
 * flags whose interaction you have to reason about. `toFlags` is the only
 * place the mapping lives.
 */
/**
 * Retrieval depth a run uses unless told otherwise.
 *
 * Mirrors `top_k` in backend/evaluation/schemas.py. Declared once so the
 * launcher's initial value and the summary's fallback cannot drift apart.
 */
export const DEFAULT_TOP_K = 5;

export const RETRIEVAL_PIPELINES = [
  {
    value: "baseline",
    label: "Baseline (dense only)",
    rrf_enabled: false,
    cross_encoder_enabled: false,
  },
  {
    value: "rrf",
    label: "RRF fusion",
    rrf_enabled: true,
    cross_encoder_enabled: false,
  },
  {
    value: "cross_encoder",
    label: "Cross-encoder rerank",
    rrf_enabled: false,
    cross_encoder_enabled: true,
  },
  {
    value: "rrf_cross_encoder",
    label: "RRF + Cross-encoder",
    rrf_enabled: true,
    cross_encoder_enabled: true,
  },
] as const;

export type RetrievalPipeline = (typeof RETRIEVAL_PIPELINES)[number]["value"];

/** The two flags a pipeline maps to. Unknown values fall back to baseline. */
export function pipelineToFlags(value: RetrievalPipeline): {
  rrf_enabled: boolean;
  cross_encoder_enabled: boolean;
} {
  const found = RETRIEVAL_PIPELINES.find((p) => p.value === value);

  return {
    rrf_enabled: found?.rrf_enabled ?? false,
    cross_encoder_enabled: found?.cross_encoder_enabled ?? false,
  };
}

/** The inverse, for labelling a finished run from its stored flags. */
export function flagsToPipelineLabel(
  rrf: boolean,
  crossEncoder: boolean,
): string {
  const found = RETRIEVAL_PIPELINES.find(
    (p) => p.rrf_enabled === rrf && p.cross_encoder_enabled === crossEncoder,
  );

  return found ? found.label : "Baseline (dense only)";
}


export type IndexType = (typeof INDEX_TYPES)[number];

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
    response = await fetch(path, { ...withAuth(init), signal });
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw caught;
    }

    throw new EvaluationApiError(
      "Could not reach the evaluation service. Is the backend running?",
    );
  }

  if (response.status === 401) {
    // The token expired or was revoked. Every screen reads the session on
    // mount, so clearing and reloading is what returns the reader to the
    // sign-in page without threading a flag through unrelated components.
    onUnauthorized();
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

/** Ask a queued or running benchmark to stop at its next question. */
export function cancelRun(
  runId: string,
  signal?: AbortSignal,
): Promise<{ run_id: string; message: string }> {
  return request<{ run_id: string; message: string }>(
    `/api/evaluation/run/${runId}/cancel`,
    { method: "POST" },
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

/* -------------------------------------------------------------------------
 * Claim-level grounding
 *
 * A separate surface from the run metrics: the rates are computed from
 * claim rows on read rather than stored on the run, because a human
 * relabelling a claim has to move the numbers immediately.
 * ---------------------------------------------------------------------- */

export type ClaimLabel = "SUPPORTED" | "UNSUPPORTED" | "INSUFFICIENT_EVIDENCE";

export interface ClaimRow {
  id: number;
  run_id: string | null;
  question_id: string;
  route: string | null;
  claim_index: number;
  /** What was judged, with unquantified intensifiers removed. */
  claim: string;
  /** What the answer actually said. */
  original: string | null;
  is_numeric: boolean;
  numeric_values: string[];
  evidence: string[];
  evaluator_label: ClaimLabel;
  evaluator_reasoning: string | null;
  evaluator_model: string | null;
  human_label: ClaimLabel | null;
  human_labeled_by: string | null;
  human_labeled_at: string | null;
}

export interface ClaimSummary {
  total_claims: number;
  supported: number;
  unsupported: number;
  insufficient_evidence: number;
  claim_support_rate: number;
  unsupported_fact_rate: number;

  validated_claims: number;
  agreement: number;
  precision: number;
  recall: number;
  f1: number;
  false_positives: number;
  false_negatives: number;
}

export function getRunClaims(
  runId: string,
  options: { unlabeled?: boolean; label?: ClaimLabel } = {},
  signal?: AbortSignal,
): Promise<ClaimRow[]> {
  const query = new URLSearchParams();

  if (options.unlabeled) query.set("unlabeled", "true");
  if (options.label) query.set("label", options.label);

  const suffix = query.toString() ? `?${query}` : "";

  return request<ClaimRow[]>(
    `/api/evaluation/runs/${runId}/claims${suffix}`,
    {},
    signal,
  );
}

export function getClaimSummary(
  runId: string,
  signal?: AbortSignal,
): Promise<ClaimSummary> {
  return request<ClaimSummary>(
    `/api/evaluation/runs/${runId}/claims/summary`,
    {},
    signal,
  );
}

/** Record one human verdict. Never touches the evaluator's own label. */
export function saveClaimLabel(
  claimId: number,
  label: ClaimLabel,
  signal?: AbortSignal,
): Promise<ClaimRow> {
  return request<ClaimRow>(
    `/api/evaluation/claims/${claimId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ human_label: label }),
    },
    signal,
  );
}
