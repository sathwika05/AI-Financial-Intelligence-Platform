import type { FinancialQueryResponse } from "../api/types";

/**
 * The console's last answer, held for the life of the browser tab.
 *
 * Root swaps App out entirely when the rail navigates: opening Ingestion
 * unmounts the console and React discards its state. So someone who ran a
 * sixty-second query, glanced at the corpus and came back found a blank
 * screen, with no way back to the answer except paying for it again.
 *
 * sessionStorage, for the lifetime it gives:
 *
 *     navigate between screens   kept
 *     refresh the page           kept
 *     close the tab              gone
 *     sign out                   gone
 *
 * Not localStorage. A report can quote personal data back out of a
 * retrieved document -- data the query masker never saw, because it was in
 * the source rather than in the question. sessionStorage dies with the
 * tab, so nothing is left sitting on a shared machine tomorrow.
 *
 * Every access is guarded. Storage throws outright in some contexts --
 * a private window with site data blocked, a thumbnailer, a browser
 * configured to refuse it -- and losing an answer is a far better outcome
 * than a console that will not render.
 */
export interface ConsoleSession {
  query: string;
  result: FinancialQueryResponse | null;
}

const KEY = "fintel.console";

// Fallback for contexts where sessionStorage throws or is absent. Gives
// the previous behaviour -- survives navigation, not a refresh -- rather
// than dropping the answer entirely.
let held: ConsoleSession | null = null;

export function readConsoleSession(): ConsoleSession | null {
  try {
    const raw = sessionStorage.getItem(KEY);

    if (raw) {
      return JSON.parse(raw) as ConsoleSession;
    }
  } catch {
    // Unreadable or unparseable: fall through to whatever is in memory.
  }

  return held;
}

export function writeConsoleSession(session: ConsoleSession): void {
  held = session;

  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // Quota, or storage refused. The in-memory copy above still covers
    // navigation between screens; only refresh-survival is lost.
  }
}

export function clearConsoleSession(): void {
  held = null;

  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to do: the in-memory copy is already gone.
  }
}
