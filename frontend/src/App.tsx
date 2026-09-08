import { clearSession, type SessionUser } from "./auth/session";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  clearConsoleSession,
  readConsoleSession,
  writeConsoleSession,
} from "./lib/consoleSession";
import { Check, Database, Scale } from "lucide-react";
import { Logo } from "./components/Logo";
import { FinancialApiError, runFinancialQuery } from "./api/client";
import type { FinancialQueryResponse } from "./api/types";
import { buildEntries } from "./lib/entries";
import { AnalysisSummary } from "./components/AnalysisSummary";
import { EvidenceSources } from "./components/EvidenceSources";
import { QueryConsole } from "./components/QueryConsole";
import { RankedList } from "./components/RankedList";
import { RankingMethodology } from "./components/RankingMethodology";
import {
  ErrorState,
  LoadingState,
  NoResultsState,
  OutOfScopeState,
  WithheldState,
} from "./components/States";
import "./App.css";
import { linkTo } from "./lib/router";

type Status = "idle" | "running" | "error" | "done";

export default function App({
  user,
  inShell = false,
  publicDemo = false,
}: {
  user: SessionUser;
  /** Rendered inside the admin rail, which already shows identity and
   *  navigation. Suppresses the masthead's own copies of both. */
  inShell?: boolean;
  /** The unauthenticated preprod deployment. Which provider served the
   *  answer is internal detail there: the visitor has no account, no
   *  provider settings, and nothing to do with the name. Signed-in
   *  analysts keep it, because for them it is provenance. */
  publicDemo?: boolean;
}) {
  // Seeded from the module-level store rather than from empty state. Root
  // unmounts this component whenever the rail navigates, so without this
  // an analyst who opened Ingestion mid-read came back to a blank console
  // and had to pay for the query again. See lib/consoleSession.
  const held = readConsoleSession();

  const [query, setQuery] = useState(held?.query ?? "");
  const [status, setStatus] = useState<Status>(held?.result ? "done" : "idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FinancialQueryResponse | null>(
    held?.result ?? null,
  );

  const requestRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef("");

  const report = result?.final_report ?? null;

  // Server-side decision, not a client one: the ranking is already absent
  // from the response by the time it gets here. Either flag alone is
  // enough — `withheld` is the explicit signal, `review.escalated` is what
  // an older response carries.
  const withheld = Boolean(report?.withheld || report?.review?.escalated);
  // Refused at the classifier, before anything ran. Checked first,
  // because it must not be described as a withheld ranking.
  const outOfScope = Boolean(report?.out_of_scope);
  const rankedCompanies = useMemo(
    () => result?.ranked_companies ?? [],
    [result],
  );

  const entries = useMemo(
    () => buildEntries(report?.top_companies ?? [], rankedCompanies),
    [report, rankedCompanies],
  );

  const runQuery = useCallback(async (raw: string) => {
    const trimmed = raw.trim();

    if (trimmed.length < 3) {
      return;
    }

    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    lastQueryRef.current = trimmed;

    setStatus("running");
    setError(null);

    try {
      const response = await runFinancialQuery(trimmed, controller.signal);

      setResult(response);
      setStatus("done");

      // Held outside the tree so navigating away and back does not lose it.
      writeConsoleSession({ query: trimmed, result: response });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        return;
      }

      setError(
        caught instanceof FinancialApiError
          ? caught.message
          : "Something went wrong while running this analysis.",
      );
      setStatus("error");
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
      }
    }
  }, []);

  const hasMethodology = Boolean(result?.scoring_result?.weights_used);
  const hasSources = Boolean(report?.sources_used);

  /**
   * Counts for the provenance list, derived from the payload itself rather
   * than estimated. Only channels whose evidence the response actually
   * carries get a count; the rest fall back to Used / Not used.
   */
  const sourceDetails = useMemo(() => {
    const documentItems = rankedCompanies.reduce(
      (total, company) => total + (company.evidence?.length ?? 0),
      0,
    );

    const companiesWithEvidence = rankedCompanies.filter(
      (company) => (company.evidence?.length ?? 0) > 0,
    ).length;

    const details: Record<string, string> = {};

    if (documentItems > 0) {
      details.vector = `${documentItems} item${documentItems === 1 ? "" : "s"}`;
    }

    if (companiesWithEvidence > 0) {
      details.company_level_evidence = `${companiesWithEvidence} compan${
        companiesWithEvidence === 1 ? "y" : "ies"
      }`;
    }

    return details;
  }, [rankedCompanies]);

  /**
   * A one-line record of what produced this result. Every part is read from
   * the response — company count, how many retrieval channels reported as
   * used, and whether a review ran — so the line shrinks rather than
   * inventing a value when something is absent.
   */
  const provenance = useMemo(() => {
    const parts: string[] = [];

    if (entries.length > 0) {
      parts.push(`${entries.length} compan${entries.length === 1 ? "y" : "ies"}`);
    }

    const usedSources = Object.values(report?.sources_used ?? {}).filter(
      (value) => value === true,
    ).length;

    if (usedSources > 0) {
      parts.push(`${usedSources} evidence source${usedSources === 1 ? "" : "s"}`);
    }

    return parts;
  }, [entries.length, report]);

  return (
    <div className="app">
      {/* The admin rail carries the brand, identity and navigation, so
          inside it the masthead would be a second copy of all three. */}
      {!inShell && (
        <header className="masthead">
          <div className="shell masthead__inner">
            <Logo size={36} />

            <span className="masthead__brand">
              <span className="masthead__title">Financial Intelligence</span>
              <span className="masthead__subtitle">
                AI-powered company research and evidence-backed financial analysis
              </span>
            </span>

            {!inShell && user.role === "admin" && (
              <a className="masthead__link" href="/evaluation" onClick={linkTo("/evaluation")}>
                Evaluation dashboard
              </a>
            )}

            {/* Absent on the public demo, which has no accounts: an empty
                address and a sign-out that ends nothing. */}
            {!inShell && user.email && (
              <>
                <span className="masthead__user">
                  <span className="masthead__user-email">{user.email}</span>
                  <span className="masthead__user-role">{user.role}</span>
                </span>

                <button
                  type="button"
                  className="masthead__signout"
                  onClick={() => {
                    clearSession();
            // The answer dies with the session, not
            // just with the page.
            clearConsoleSession();
                    window.location.reload();
                  }}
                >
                  Sign out
                </button>
              </>
            )}
          </div>
        </header>
      )}

      <main className="shell app__main">
        {status === "idle" && (
          <div className="hero">
            <h1 className="hero__title">
              Research companies{" "}
              <span className="hero__accent">with evidence</span>.
            </h1>
            <p className="hero__lede">
              Ask a financial question and get ranked companies, key metrics,
              and evidence-backed analysis.
            </p>

            {/* Sets the expectation before the first click rather than
                after it. The loading state already shows elapsed time and
                stages, so this only needs to explain why that number is
                larger here than it would be in production. */}
            {publicDemo && (
              <p className="hero__note">
                This public demo runs on a free-tier model, so answers take
                noticeably longer than the production system.
              </p>
            )}
          </div>
        )}

        <QueryConsole
          value={query}
          onChange={setQuery}
          onSubmit={() => void runQuery(query)}
          isRunning={status === "running"}
          compact={status === "done"}
          publicDemo={publicDemo}
        />

        {status === "done" && (
          <div className="app__clearrow">
            <span className="app__held">
              Showing your last answer. It survives a refresh, and clears when you sign out or close the tab.
            </span>
            <button
              type="button"
              className="app__clear"
              onClick={() => {
                clearConsoleSession();
                setResult(null);
                setStatus("idle");
                setError(null);
                setQuery("");
              }}
            >
              Clear
            </button>
          </div>
        )}

        {status === "running" && (
          <div className="app__block">
            <LoadingState />
          </div>
        )}

        {status === "error" && error && (
          <div className="app__block">
            <ErrorState
              message={error}
              onRetry={() => void runQuery(lastQueryRef.current || query)}
            />
          </div>
        )}

        {/* A withheld answer replaces the analysis rather than annotating
            it. The summary, the ranking and the methodology all describe a
            result the server declined to send, and rendering their empty
            shells around a warning reads as a broken screen. */}
        {status === "done" && outOfScope && (
          <div className="app__block">
            <OutOfScopeState notice={report?.review?.notice} />
          </div>
        )}

        {status === "done" && !outOfScope && withheld && (
          <div className="app__block">
            <WithheldState
              notice={report?.review?.notice}
              confidence={report?.overall_confidence}
              reason={report?.review?.decision}
            />
          </div>
        )}

        {status === "done" && !withheld && !outOfScope && (
          <>
            {report && (
              <div className="app__block">
                <AnalysisSummary
                  report={report}
                  provider={publicDemo ? null : result?.provider}
                />
              </div>
            )}

            {entries.length === 0 ? (
              <div className="app__block">
                <NoResultsState />
              </div>
            ) : (
              <div className="app__block">
                {provenance.length > 0 && (
                  <p className="app__provenance">
                    {provenance.join(" · ")}
                    {report?.review && (
                      <span className="app__provenance-check">
                        {" · "}Reviewed
                        <Check size={11} aria-hidden="true" />
                      </span>
                    )}
                  </p>
                )}

                <RankedList
                  entries={entries}
                  comparisonCompanies={rankedCompanies}
                />
              </div>
            )}

            {(hasMethodology || hasSources) && (
              <div className="app__block app__columns">
                {hasMethodology && (
                  <section className="panel app__column">
                    <h2 className="block-title">
                      <Scale size={14} className="block-title__icon" aria-hidden="true" />
                      Ranking methodology
                    </h2>
                    <RankingMethodology
                      weights={result?.scoring_result?.weights_used}
                    />
                  </section>
                )}

                {hasSources && (
                  <section className="panel app__column">
                    <h2 className="block-title">
                      <Database size={14} className="block-title__icon" aria-hidden="true" />
                      Evidence used
                    </h2>
                    <p className="app__column-note">
                      Which retrieval channels contributed to this analysis.
                    </p>
                    <EvidenceSources
                      sources={report?.sources_used}
                      details={sourceDetails}
                    />
                  </section>
                )}
              </div>
            )}
          </>
        )}
      </main>

      <footer className="app__footer">
        <div className="shell">
          <p className="app__disclaimer">
            For research and informational purposes only. Not investment advice.
          </p>
        </div>
      </footer>
    </div>
  );
}
