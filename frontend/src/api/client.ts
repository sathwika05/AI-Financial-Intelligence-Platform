import { withAuth } from "../auth/session";
import type { FinancialQueryResponse } from "./types";

const ENDPOINT = "/api/retrieve/financial";

/** Backend constraint: query is `Field(min_length=3, max_length=500)`. */
export const QUERY_MIN_LENGTH = 3;
export const QUERY_MAX_LENGTH = 500;

export class FinancialApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "FinancialApiError";
    this.status = status;
  }
}

/** Pull a readable message out of FastAPI's error shapes. */
async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();

    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;

      if (typeof detail === "string") {
        return detail;
      }

      // 422 validation errors arrive as a list of objects.
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : null,
          )
          .filter((msg): msg is string => Boolean(msg));

        return messages.length > 0 ? messages.join(". ") : null;
      }
    }
  } catch {
    // Body was not JSON; fall through to the status-based message.
  }

  return null;
}

export async function runFinancialQuery(
  query: string,
  signal?: AbortSignal,
): Promise<FinancialQueryResponse> {
  let response: Response;

  try {
    response = await fetch(ENDPOINT, {
      ...withAuth({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }

    throw new FinancialApiError(
      "Could not reach the analysis service. Check that the API is running, then try again.",
    );
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);

    throw new FinancialApiError(
      detail ??
        (response.status >= 500
          ? "The analysis service failed to complete this request. Try again in a moment."
          : `Request rejected (${response.status}).`),
      response.status,
    );
  }

  try {
    return (await response.json()) as FinancialQueryResponse;
  } catch {
    throw new FinancialApiError(
      "The analysis service returned a response that could not be read.",
      response.status,
    );
  }
}
