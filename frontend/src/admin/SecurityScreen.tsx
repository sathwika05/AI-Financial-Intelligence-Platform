import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, ShieldX } from "lucide-react";
import {
  AdminApiError,
  listSecurityEvents,
  type SecurityEvent,
} from "./api";
import "./AdminScreens.css";
import "./Security.css";

/**
 * What the guards caught.
 *
 * Every guard already wrote its decision into system_logs; nothing read
 * those rows, so the only way to tell a filter that works from one that
 * never fires was a psql prompt. This is that reader.
 *
 * Blocked and masked are rendered differently on purpose. One refused the
 * request; the other let it through with the personal data removed. Making
 * them look alike would suggest the pipeline refuses anything it finds,
 * which is the opposite of how the patterns are tuned — "ignore the
 * previous quarter" is a real question and it passes.
 *
 * Polls rather than waiting for a refresh: the screen is watched while
 * someone runs queries in another tab, and a table that only fills when
 * you click is a table that looks broken.
 */

const POLL_MS = 4000;

export function SecurityScreen() {
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);

  // Which ids were already on screen, so a row that just arrived can be
  // marked. A ref rather than state: it must not itself cause a render.
  const seen = useRef<Set<number> | null>(null);
  const [fresh, setFresh] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    try {
      const feed = await listSecurityEvents();

      if (seen.current === null) {
        // First load. Nothing is "new" — everything predates the visit.
        seen.current = new Set(feed.events.map((e) => e.id));
      } else {
        const arrived = feed.events
          .map((e) => e.id)
          .filter((id) => !seen.current!.has(id));

        if (arrived.length) {
          arrived.forEach((id) => seen.current!.add(id));
          setFresh(new Set(arrived));
        }
      }

      setEvents(feed.events);
      setStatus("ready");
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not load the security log.",
      );
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();

    const timer = window.setInterval(() => void load(), POLL_MS);

    return () => window.clearInterval(timer);
  }, [load]);

  const blocked = events.filter((e) => e.action === "blocked").length;
  const masked = events.length - blocked;

  return (
    <div className="screen">
      <header className="screen__head">
        <h1 className="screen__title">Security</h1>
      </header>

      {status !== "loading" && (
        <div className="sec__tally">
          <span className="sec__tally-item">
            <ShieldX size={14} className="sec__icon-blocked" aria-hidden="true" />
            <b className="num">{blocked}</b> blocked
          </span>
          <span className="sec__tally-item">
            <ShieldCheck size={14} className="sec__icon-masked" aria-hidden="true" />
            <b className="num">{masked}</b> masked
          </span>
          <span className="sec__tally-live">updating live</span>
        </div>
      )}

      {error && <p className="screen__error">{error}</p>}

      {status === "loading" && <p className="screen__note">Loading…</p>}

      {status !== "loading" && (
        <div className="screen__table-wrap">
          <table className="screen__table sec__table">
            <thead>
              <tr>
                <th>When</th>
                <th>Outcome</th>
                <th>Query</th>
                <th>Detected by</th>
              </tr>
            </thead>
            <tbody>
              {/* The columns show before anything has been caught, so the
                  screen reads as waiting rather than unfinished — and the
                  first row lands in a shape the reader already knows. */}
              {events.length === 0 && (
                <tr>
                  <td className="sec__waiting" colSpan={4}>
                    Nothing caught yet. Prompt injections, personal data
                    of any kind, and rate limits appear here within a few
                    seconds of being caught.
                  </td>
                </tr>
              )}

              {events.map((event) => (
                <tr
                  key={event.id}
                  className={fresh.has(event.id) ? "sec__row--new" : undefined}
                >
                  <td className="sec__when num">
                    {event.created_at
                      ? new Date(event.created_at).toLocaleTimeString()
                      : "—"}
                  </td>
                  {/* The outcome leads, the rule names itself underneath.
                      A pill reading "Prompt injection" says what was found;
                      it never said what happened to the request, which is
                      the first thing anyone reading this table wants. */}
                  <td>
                    <span
                      className={`screen__pill sec__pill sec__pill--${event.action}`}
                      title={event.explains}
                    >
                      {event.action === "blocked" ? "Blocked" : "Masked"}
                    </span>
                    <span className="sec__rule">{event.label}</span>
                  </td>
                  <td className="sec__query">
                    {event.query || "—"}
                    {/* Types, never values. The point of the row is that
                        the value is gone — reprinting it here would undo
                        exactly what the guard did. */}
                    {event.removed.length > 0 && (
                      <span className="sec__removed">
                        removed
                        {event.removed.map((field) => (
                          <span key={field} className="sec__removed-field">
                            {field}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td className="sec__detail" title={event.detail}>
                    {/* The clamp lives on this span, not the cell. Applied
                        to a <td> it replaces the cell's table-cell display
                        and the row's borders stop rendering across it. */}
                    <span className="sec__detail-text">{event.detail}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
