import { useCallback, useMemo, useRef, useState } from "react";
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

type Status = "idle" | "running" | "error" | "done";

export default function App() {
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

  return (
    <div className="app">
      <header className="masthead">
        <div className="shell masthead__inner">
          <span className="masthead__mark" aria-hidden="true" />

          <span className="masthead__brand">
            <span className="masthead__title">Financial Intelligence</span>
            <span className="masthead__subtitle">
              AI-powered company research and evidence-backed financial analysis
            </span>
          </span>

          <a className="masthead__link" href="#/evaluation">
            Evaluation dashboard
          </a>
        </div>
      </header>

      <main className="shell app__main">
        {status === "idle" && (
          <div className="hero">
            <h1 className="hero__title">
              Research any <span className="hero__accent">company question</span>
              .
            </h1>
            <p className="hero__lede">
              Every answer ranks companies against the question you asked, shows
              the figures behind the ranking, and links each conclusion to the
              evidence it came from.
            </p>
          </div>
        )}

        <QueryConsole
          value={query}
          onChange={setQuery}
          onSubmit={() => void runQuery(query)}
          isRunning={status === "running"}
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
                    <h2 className="block-title">How ranking works</h2>
                    <RankingMethodology
                      weights={result?.scoring_result?.weights_used}
                    />
                  </section>
                )}

                {hasSources && (
                  <section className="panel app__column">
                    <h2 className="block-title">Evidence sources</h2>
                    <p className="app__column-note">
                      What this analysis drew on.
                    </p>
                    <EvidenceSources sources={report?.sources_used} />
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
