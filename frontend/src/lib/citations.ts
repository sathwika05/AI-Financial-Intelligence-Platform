export interface TextSegment {
  kind: "text" | "citation";
  value: string;
}

/**
 * Split a company summary into plain text and citation tokens.
 *
 * Only bracketed tokens that match a known citation id are treated as
 * citations, so ordinary bracketed prose is never mistaken for one. Summaries
 * with no citations (observed on SENTIMENT queries) pass through untouched.
 */
export function splitCitations(
  text: string | null | undefined,
  knownIds: ReadonlySet<string>,
): TextSegment[] {
  if (!text) {
    return [];
  }

  if (knownIds.size === 0) {
    return [{ kind: "text", value: text }];
  }

  const segments: TextSegment[] = [];
  // Responses cite with brackets ("[NVDA-metrics-1]") on some queries and
  // parentheses ("(NVDA-metrics-1)") on others; both are recognised.
  const pattern = /\[([^[\]]+)\]|\(([^()]+)\)/g;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const token = (match[1] ?? match[2] ?? "").trim();

    if (!knownIds.has(token)) {
      continue;
    }

    const start = match.index ?? 0;

    if (start > cursor) {
      segments.push({ kind: "text", value: text.slice(cursor, start) });
    }

    segments.push({ kind: "citation", value: token });
    cursor = start + match[0].length;
  }

  if (cursor < text.length) {
    segments.push({ kind: "text", value: text.slice(cursor) });
  }

  return segments;
}
