/**
 * Translation from backend vocabulary to the words a research user reads.
 * Raw values are preserved by callers for technical detail/tooltips.
 */

/** Canonical factor order; unknown factors are appended, never dropped. */
export const FACTOR_ORDER = [
  "valuation",
  "growth",
  "relevance",
  "sentiment",
] as const;

export function orderFactors(keys: string[]): string[] {
  const known = FACTOR_ORDER.filter((factor) => keys.includes(factor));
  const extra = keys.filter(
    (key) => !FACTOR_ORDER.includes(key as (typeof FACTOR_ORDER)[number]),
  );

  return [...known, ...extra];
}

function titleCase(value: string): string {
  return value
    .replace(/[_\-:]+/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

export function factorLabel(factor: string): string {
  return titleCase(factor);
}

/** MIXED -> "Mixed Analysis". Unknown intents are title-cased, not dropped. */
export function intentLabel(intent: string | null | undefined): string | null {
  if (!intent) {
    return null;
  }

  const map: Record<string, string> = {
    MIXED: "Mixed Analysis",
    VALUATION: "Valuation Analysis",
    GROWTH: "Growth Analysis",
    SENTIMENT: "Sentiment Analysis",
  };

  return map[intent.trim().toUpperCase()] ?? `${titleCase(intent)} Analysis`;
}

export function evidenceQualityLabel(
  quality: string | null | undefined,
): string | null {
  return quality ? titleCase(quality) : null;
}

export type Tone = "positive" | "caution" | "negative" | "neutral";

export function evidenceQualityTone(quality: string | null | undefined): Tone {
  switch ((quality ?? "").trim().toLowerCase()) {
    case "high":
      return "positive";
    case "medium":
      return "caution";
    case "low":
      return "negative";
    default:
      return "neutral";
  }
}

/**
 * Tone for a backend recommendation. Unknown future values fall back to
 * neutral rather than being coerced into a buy/sell reading.
 */
export function recommendationTone(
  recommendation: string | null | undefined,
): Tone {
  const value = (recommendation ?? "").trim().toLowerCase();

  if (value.includes("buy")) {
    return "positive";
  }

  if (value.includes("sell") || value.includes("avoid")) {
    return "negative";
  }

  if (value.includes("hold")) {
    return "caution";
  }

  return "neutral";
}

/**
 * How strongly a company matches the research question.
 *
 * The backend answers in investment vocabulary — its prompt allows exactly
 * Strong Buy / Buy / Hold / Sell / Strong Sell — but this product researches
 * and ranks companies, it does not advise on trades. The same judgement is
 * therefore read as match strength against the question that was asked.
 *
 * Purely a relabelling: the ordering the backend expressed is preserved, and
 * callers keep the raw value for the tooltip so nothing is hidden.
 */
export function matchLabel(
  recommendation: string | null | undefined,
): string | null {
  const value = (recommendation ?? "").trim().toLowerCase();

  if (!value) {
    return null;
  }

  if (value.includes("strong") && value.includes("buy")) {
    return "Strong Match";
  }

  if (value.includes("buy")) {
    return "Good Match";
  }

  if (value.includes("hold")) {
    return "Moderate Match";
  }

  if (value.includes("sell") || value.includes("avoid")) {
    return "Weak Match";
  }

  // An unrecognised verdict is shown as returned rather than forced into a
  // match level it may not mean.
  return titleCase(value);
}

/** Match strength on a 0–3 scale, for the strength indicator. */
export function matchStrength(
  recommendation: string | null | undefined,
): number | null {
  switch (matchLabel(recommendation)) {
    case "Strong Match":
      return 3;
    case "Good Match":
      return 2;
    case "Moderate Match":
      return 1;
    case "Weak Match":
      return 0;
    default:
      return null;
  }
}

/** metrics -> "Financial Metrics", sql -> "Structured Financial Data", ... */
export function sourceLabel(source: string | null | undefined): string {
  const map: Record<string, string> = {
    metrics: "Financial Metrics",
    sql: "Structured Financial Data",
    vector: "Document Evidence",
    market: "Market Data",
    company_level_evidence: "Company-Level Evidence",
  };

  const key = (source ?? "").trim().toLowerCase();

  return map[key] ?? (source ? titleCase(source) : "Evidence");
}

export interface ReadableFlag {
  /** User-facing sentence. */
  label: string;
  /** Original backend string, kept for the technical detail tooltip. */
  raw: string;
  /** Whether this flag concerns unverified sentiment evidence. */
  sentimentRelated: boolean;
}

const FLAG_MESSAGES: Array<{ match: RegExp; message: string }> = [
  {
    // Any flagged recent-earnings-sentiment code: the flag list only ever
    // carries limitations, so these all mean the reading is unverified.
    match: /RECENT_EARNINGS_SENTIMENT/,
    message: "Recent earnings sentiment could not be sufficiently verified",
  },
  {
    match: /SENTIMENT_SCORE_NOT_SUPPORTED_BY_NARRATIVE_EVIDENCE/,
    message: "The sentiment score is not backed by document evidence",
  },
  {
    match: /WEAK_RELEVANCE_EVIDENCE/,
    message: "Limited supporting evidence",
  },
  {
    match: /MISSING_MARKET_CAP|MARKET_CAP_UNAVAILABLE/,
    message: "Market capitalization unavailable",
  },
  {
    match: /MISSING_METRIC/,
    message: "A financial metric was unavailable",
  },
];

/** True when a flag is written as prose rather than as a code. */
function looksLikeSentence(flag: string): boolean {
  return /\s/.test(flag.trim()) && /[a-z]/.test(flag);
}

/**
 * Split "WEAKLY_SUPPORTED_RANK: AMD's revenue growth is higher" into its code
 * and its sentence. Responses use this shape alongside bare codes and bare
 * sentences, and the code prefix should never reach the reader.
 */
function splitCodedSentence(
  raw: string,
): { code: string; sentence: string | null } {
  // Pure code form with a category prefix, e.g.
  // "unsupported_claim:positive_recent_earnings_sentiment".
  if (!/\s/.test(raw) && raw.includes(":")) {
    return { code: raw.split(":").pop()!.trim(), sentence: null };
  }

  const match = /^([A-Za-z][A-Za-z0-9_\s-]*?):\s*(\S.*)$/s.exec(raw);

  if (match && /^[A-Z][A-Z0-9_\s-]*$/.test(match[1].trim())) {
    return { code: match[1].trim(), sentence: match[2].trim() };
  }

  return { code: raw, sentence: null };
}

/**
 * Turn a backend flag into a readable warning.
 *
 * Handles all three shapes seen in real responses: SCREAMING_SNAKE codes,
 * `prefix:suffix` codes, and complete sentences (passed through unchanged).
 */
export function readFlag(flag: string): ReadableFlag {
  const raw = flag.trim();
  const { code, sentence } = splitCodedSentence(raw);
  const normalized = code.toUpperCase().replace(/[\s-]+/g, "_");
  const sentimentRelated = /sentiment/i.test(raw);

  for (const { match, message } of FLAG_MESSAGES) {
    if (match.test(normalized)) {
      return { label: message, raw, sentimentRelated };
    }
  }

  // "CODE: explanation" -> show the explanation, keep the code in the tooltip.
  if (sentence) {
    return { label: sentence, raw, sentimentRelated };
  }

  if (looksLikeSentence(raw)) {
    return { label: raw, raw, sentimentRelated };
  }

  // Unknown bare code: humanise rather than exposing raw SCREAMING_SNAKE.
  const humanised = titleCase(code);

  return {
    label: humanised.charAt(0).toUpperCase() + humanised.slice(1),
    raw,
    sentimentRelated,
  };
}

/**
 * Whether any flag says the sentiment reading lacks support, which means the
 * numeric sentiment score must not be presented as verified sentiment.
 */
export function hasUnsupportedSentiment(
  flags: string[] | null | undefined,
): boolean {
  return (flags ?? []).some((flag) => readFlag(flag).sentimentRelated);
}
