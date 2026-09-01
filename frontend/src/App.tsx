import { clearSession, type SessionUser } from "./auth/session";
import { useCallback, useMemo, useRef, useState } from "react";
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
} from "./components/States";
import "./App.css";
import { linkTo } from "./lib/router";

type Status = "idle" | "running" | "error" | "done";

export default function App({
  user,
  inShell = false,
}: {
  user: SessionUser;
  /** Rendered inside the admin rail, which already shows identity and
   *  navigation. Suppresses the masthead's own copies of both. */
  inShell?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FinancialQueryResponse | null>(null);

  const requestRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef("");

  const report = result?.final_report ?? null;
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
          </div>
        )}

        <QueryConsole
          value={query}
          onChange={setQuery}
          onSubmit={() => void runQuery(query)}
          isRunning={status === "running"}
          compact={status === "done"}
        />

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

        {status === "done" && (
          <>
            {report && (
              <div className="app__block">
                <AnalysisSummary report={report} provider={result?.provider} />
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
