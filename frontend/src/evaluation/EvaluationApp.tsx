import { useMemo, useState } from "react";
import { useHashRoute } from "../lib/router";
import { findPreviousRun, isTerminal } from "./metrics";
import { useRunPolling, useRuns } from "./useEvaluationData";
import { shortRunId } from "./format";
import {
  DEFAULT_VIEW,
  Sidebar,
  isValidView,
  NAV_SECTIONS,
} from "./components/Sidebar";
import { RunBar } from "./components/RunBar";
import { EmptyState } from "./components/primitives";
import { CompareView } from "./views/CompareView";
import { ErrorView } from "./views/ErrorView";
import { GroupView } from "./views/GroupView";
import { MetricsView } from "./views/MetricsView";
import { PerQuestionView } from "./views/PerQuestionView";
import { ProvidersView } from "./views/ProvidersView";
import { RetrievalModesView } from "./views/RetrievalModesView";
import { RunsView } from "./views/RunsView";
import { SettingsView } from "./views/SettingsView";
import { SummaryView } from "./views/SummaryView";
import { TrendView } from "./views/TrendView";
import "./eval.css";

/**
 * The evaluation dashboard.
 *
 * Holds the two pieces of state every view reads — which section is open and
 * which run is selected — and owns the polling that keeps an in-flight
 * benchmark's row current. Each view below is a pure function of the run list.
 */

const VIEW_TITLES = new Map(
  NAV_SECTIONS.flatMap((section) => section.items).map((item) => [
    item.id,
    item.label,
  ]),
);

/** `#/evaluation/runs` → `runs`; anything unrecognized falls back to Summary. */
function viewFromPath(path: string): string {
  const segment = path.replace(/^\/evaluation\/?/, "").split("/")[0];

  return segment && isValidView(segment) ? segment : DEFAULT_VIEW;
}

export default function EvaluationApp() {
  const [path, navigate] = useHashRoute();
  const view = viewFromPath(path);

  const { runs, status, error, isRefreshing, reload } = useRuns();
  const hasActiveRun = useRunPolling(runs, reload);

  const [runChoice, setRunChoice] = useState<string | null>(null);

  // Follow the newest run until the operator picks one explicitly; after that
  // their selection stands. Deriving rather than storing means a choice that
  // falls out of the history window silently reverts to the newest run.
  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === runChoice) ?? runs[0] ?? null,
    [runs, runChoice],
  );

  const selectedRunId = selectedRun?.run_id ?? null;

  const previousRun = useMemo(
    () => findPreviousRun(runs, selectedRun),
    [runs, selectedRun],
  );

  const openRun = (runId: string) => {
    setRunChoice(runId);
    navigate("/evaluation/summary");
  };

  const inFlight = runs.filter((run) => !isTerminal(run.status));

  const body = () => {
    if (status === "loading") {
      return <p className="ev-note">Loading benchmark runs…</p>;
    }

    if (status === "error") {
      return (
        <EmptyState
          title="Could not reach the evaluation service"
          detail={error ?? "The runs endpoint did not respond."}
          action={
            <button
              type="button"
              className="ev-btn ev-btn--ghost"
              onClick={reload}
            >
              Try again
            </button>
          }
        />
      );
    }

    switch (view) {
      case "runs":
        return (
          <RunsView
            runs={runs}
            selectedRunId={selectedRunId}
            onSelect={openRun}
          />
        );

      case "compare":
        return <CompareView runs={runs} />;

      case "metrics":
        return <MetricsView run={selectedRun} previous={previousRun} />;

      case "retrieval":
        return (
          <GroupView
            runs={runs}
            field="retrieval_mode"
            title="Retrieval Mode Comparison"
            emptyDetail="No completed runs yet. Each mode needs at least one finished benchmark before it can be compared."
          />
        );

      case "retrieval-modes":
        return <RetrievalModesView runs={runs} />;

      case "datasets":
        return (
          <GroupView
            runs={runs}
            field="dataset"
            title="Datasets"
            emptyDetail="No completed runs yet. A dataset appears here once a benchmark has finished against it."
          />
        );

      case "question-sets":
        return (
          <GroupView
            runs={runs}
            field="question_set"
            title="Question Sets"
            emptyDetail="No completed runs yet. A question set appears here once a benchmark has finished against it."
          />
        );

      case "per-question":
        return <PerQuestionView run={selectedRun} />;

      case "settings":
        return <SettingsView runs={runs} />;

      case "models":
        return (
          <GroupView
            runs={runs}
            field="model"
            title="Model Comparison"
            emptyDetail="No completed runs yet. Run the same question set against different providers to compare their model tiers."
          />
        );

      case "trends":
        return <TrendView runs={runs} />;

      case "errors":
        return <ErrorView runs={runs} />;

      case "providers":
        return <ProvidersView />;

      default:
        return (
          <SummaryView
            run={selectedRun}
            previous={previousRun}
            runs={runs}
            onNavigate={(next) => navigate(`/evaluation/${next}`)}
          />
        );
    }
  };

  return (
    <div className="ev-app">
      <Sidebar
        activeView={view}
        onNavigate={(next) => navigate(`/evaluation/${next}`)}
      />

      <div className="ev-main">
        <RunBar
          onLaunched={(runId) => {
            setRunChoice(runId);
            reload();
          }}
          onRefresh={reload}
          isRefreshing={isRefreshing}
        />

        {hasActiveRun && (
          <div className="ev-banner" role="status">
            <span className="ev-banner__spinner" aria-hidden="true" />
            {inFlight.length === 1
              ? `${shortRunId(inFlight[0].run_id)} is ${inFlight[0].status}. This view refreshes automatically.`
              : `${inFlight.length} runs are in progress. This view refreshes automatically.`}
          </div>
        )}

        {error && status === "ready" && (
          <div className="ev-banner ev-banner--error" role="status">
            {error} Showing the last successful load.
          </div>
        )}

        <main className="ev-content">
          <h1 className="ev-content__title">
            {VIEW_TITLES.get(view) ?? "Summary"}
          </h1>

          {body()}
        </main>
      </div>
    </div>
  );
}
