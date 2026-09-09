/**
 * Display formatting.
 *
 * Every metric on this screen may legitimately be null — a run that failed
 * before an evaluator ran, or an evaluator that did not apply to the chosen
 * question set. Null renders as an em dash everywhere, never as zero, so a
 * missing measurement is never mistaken for a bad one.
 */

export const EM_DASH = "—";

export function formatScore(value: number | null | undefined): string {
  return value == null ? EM_DASH : value.toFixed(2);
}

export function formatPercent(
  value: number | null | undefined,
  digits = 1,
): string {
  if (value == null) {
    return EM_DASH;
  }

  // Every rate the backend stores is a 0–1 fraction.
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms == null) {
    return EM_DASH;
  }

  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

/**
 * Latency for chart labels, where width is scarce.
 *
 * `formatLatency` keeps two decimals, which reads as "146.60s" on a slow run
 * and collides with the neighbouring bar's label. Precision is dropped as the
 * magnitude grows, so a label is never more than five characters.
 */
export function formatLatencyCompact(ms: number | null | undefined): string {
  if (ms == null) {
    return EM_DASH;
  }

  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }

  const seconds = ms / 1000;

  return seconds < 10 ? `${seconds.toFixed(2)}s` : `${Math.round(seconds)}s`;
}

export function formatCost(usd: number | null | undefined): string {
  if (usd == null) {
    return EM_DASH;
  }

  // Sub-cent totals are common on small question sets, so fixed 2dp would
  // flatten most runs to $0.00.
  const digits = usd !== 0 && Math.abs(usd) < 0.01 ? 4 : 2;

  return `$${usd.toFixed(digits)}`;
}

export function formatCount(value: number | null | undefined): string {
  return value == null ? EM_DASH : value.toLocaleString();
}

/** Backend timestamps are naive UTC; append Z so they are not read as local. */
function parseTimestamp(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }

  const normalized = /[Z+]|-\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);

  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateTime(value: string | null | undefined): string {
  const parsed = parseTimestamp(value);

  if (!parsed) {
    return EM_DASH;
  }

  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value: string | null | undefined): string {
  const parsed = parseTimestamp(value);

  if (!parsed) {
    return EM_DASH;
  }

  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function timestampMs(value: string | null | undefined): number | null {
  return parseTimestamp(value)?.getTime() ?? null;
}

/** Wall-clock span between run creation and completion, as HH:MM:SS. */
export function formatDuration(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
): string {
  const start = timestampMs(startedAt);
  const end = timestampMs(completedAt);

  if (start == null || end == null || end < start) {
    return EM_DASH;
  }

  const totalSeconds = Math.round((end - start) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

/** "RUN-2F3A9C" — the full UUID is too wide for a header or a table cell. */
export function shortRunId(runId: string): string {
  return `RUN-${runId.replace(/-/g, "").slice(0, 6).toUpperCase()}`;
}

/** Turns "small=gpt-x, medium=gpt-y, large=gpt-z" into its three parts. */
export function parseModelSnapshot(
  snapshot: string | null | undefined,
): { tier: string; model: string }[] {
  if (!snapshot) {
    return [];
  }

  return snapshot
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [tier, ...rest] = part.split("=");

      return { tier: tier.trim(), model: rest.join("=").trim() || EM_DASH };
    });
}

export function titleCase(value: string): string {
  return value
    .split(/[\s_+-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Question sets are stored as their registry keys. Only "all" needs more
 * than title-casing — on its own it reads as a filter state rather than as
 * the name of a set.
 */
export function questionSetLabel(name: string | null | undefined): string {
  if (!name) {
    return EM_DASH;
  }

  return name === "all" ? "All Sets" : titleCase(name);
}

/**
 * Retrieval modes are stored as the identifiers the pipeline uses, and
 * title-casing them loses the part that matters — "hybrid+reranker" would
 * read as "Hybrid Reranker", which is a different strategy.
 */
const RETRIEVAL_LABELS: Record<string, string> = {
  "hybrid+reranker": "Hybrid + Reranker",
  hybrid: "Hybrid",
  vector: "Vector",
  sql: "SQL",
};

export function retrievalLabel(mode: string | null | undefined): string {
  if (!mode) {
    return EM_DASH;
  }

  return RETRIEVAL_LABELS[mode] ?? titleCase(mode);
}


/**
 * The retrieval variant a run used, or null for the baseline.
 *
 * Null rather than "baseline" on purpose: every run recorded before these
 * flags existed used the baseline pipeline, and tagging all of history with
 * a new badge would imply a distinction that did not exist at the time.
 */
/**
 * A short pill for a run whose LLM blend weight was not the default.
 *
 * Null on the default, matching retrievalPipelineLabel below: a run that
 * changed nothing gets no pill, so the ones that did stand out in a list.
 * Without this the four ablation arms render identically and there is no
 * way to tell which was which — which would defeat the point of running
 * them.
 *
 * Null and 0.0 are different readings and are shown differently. Null is
 * "did not choose", so the ranker's default applied. 0.0 is "chose to
 * remove the model from the ranking", which is the whole ablation.
 */
export function blendPillLabel(run: {
  llm_blend_weight?: number | null;
}): string | null {
  if (run.llm_blend_weight === null || run.llm_blend_weight === undefined) {
    return null;
  }

  if (run.llm_blend_weight === 0) {
    return "blend off";
  }

  return `blend ${run.llm_blend_weight.toFixed(2)}`;
}


export function retrievalPipelineLabel(run: {
  rrf_enabled?: boolean;
  cross_encoder_enabled?: boolean;
}): string | null {
  const parts: string[] = [];

  if (run.rrf_enabled) {
    parts.push("RRF");
  }

  if (run.cross_encoder_enabled) {
    parts.push("CE");
  }

  return parts.length > 0 ? parts.join(" + ") : null;
}
