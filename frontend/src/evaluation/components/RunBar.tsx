import { useCallback, useMemo, useState } from "react";
import { CircleStop, PlayCircle, RefreshCw } from "lucide-react";
import {
  DATASETS,
  EvaluationApiError,
  INDEX_TYPES,
  QUESTION_SETS,
  RETRIEVAL_MODES,
  RETRIEVAL_PIPELINES,
  cancelRun,
  pipelineToFlags,
  triggerRun,
  type IndexType,
  type QuestionSet,
  type RetrievalPipeline,
} from "../api";
import {
  questionSetLabel,
  retrievalLabel,
} from "../format";
import { useProviderModels, useProviders } from "../useEvaluationData";

/**
 * The benchmark launcher.
 *
 * The form mirrors `RunRequest` exactly. Note the absent model selector: the
 * request carries only a provider, and the backend resolves that provider's
 * enabled small / medium / large tiers itself. Those resolved tiers are shown
 * read-only beside the selector so the operator can see what will run.
 */

const TIER_ORDER = ["small", "medium", "large"];

export function RunBar({
  onLaunched,
  onRefresh,
  isRefreshing,
  activeRunCount = 0,
  activeRunIds = [],
}: {
  onLaunched: (runId: string) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  /** Runs still queued or running. The backend rejects a duplicate outright;
   *  this stops the reader from queuing one in the first place. */
  activeRunCount?: number;
  /** Those same runs, so Stop knows what to cancel. */
  activeRunIds?: string[];
}) {
  const {
    providers,
    status: providerStatus,
    error: providerError,
    reload: reloadProviders,
  } = useProviders();

  // Refresh means "re-read everything the bar shows", not just the run list.
  // The provider fetch is the one most likely to have failed, since it only
  // happens on mount.
  const handleRefresh = useCallback(() => {
    reloadProviders();
    onRefresh();
  }, [reloadProviders, onRefresh]);

  // Null means "no explicit choice yet", which resolves to the provider's own
  // default below. Deriving rather than seeding avoids a render pass where
  // the selector is blank.
  const [providerChoice, setProviderChoice] = useState<string | null>(null);
  const [dataset, setDataset] = useState<string>(DATASETS[0]);
  const [retrievalMode, setRetrievalMode] = useState<string>(
    RETRIEVAL_MODES[0],
  );
  // Not sent with the run: RunRequest has no index_type. See INDEX_TYPES.
  const [indexType, setIndexType] = useState<IndexType>(INDEX_TYPES[0]);
  const [questionSet, setQuestionSet] = useState<QuestionSet>(
    QUESTION_SETS[0],
  );
  const [topK, setTopK] = useState(5);

  // Retrieval pipeline switches. Both off is the baseline, so the default
  // launch is the pipeline as it has always run.
  const [isStopping, setIsStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [pipeline, setPipeline] =
    useState<RetrievalPipeline>("baseline");

  const [isLaunching, setIsLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launchNotice, setLaunchNotice] = useState<string | null>(null);

  // Only enabled providers can run a benchmark; the default one is preselected.
  const selectableProviders = useMemo(
    () => providers.filter((provider) => provider.is_enabled),
    [providers],
  );

  const providerId = useMemo(() => {
    const chosen = selectableProviders.find(
      (provider) => provider.id === providerChoice,
    );

    if (chosen) {
      return chosen.id;
    }

    const preferred =
      selectableProviders.find((provider) => provider.is_default) ??
      selectableProviders[0];

    return preferred?.id ?? "";
  }, [providerChoice, selectableProviders]);

  const { models } = useProviderModels(providerId || null);

  const tierSummary = useMemo(() => {
    const enabled = models.filter((model) => model.is_enabled);

    if (enabled.length === 0) {
      return null;
    }

    return TIER_ORDER.map(
      (tier) =>
        enabled.find((model) => model.tier === tier)?.model_name ?? "—",
    ).join(" / ");
  }, [models]);

  const launch = async () => {
    if (!providerId) {
      return;
    }

    setIsLaunching(true);
    setLaunchError(null);
    setLaunchNotice(null);

    try {
      const accepted = await triggerRun({
        provider_id: providerId,
        dataset,
        retrieval_mode: retrievalMode,
        question_set: questionSet,
        company_filter: "all",
        top_k: topK,
        ...pipelineToFlags(pipeline),
      });

      setLaunchNotice(
        `Queued on ${accepted.provider_name} · ${Object.entries(accepted.models)
          .map(([tier, model]) => `${tier}=${model}`)
          .join(", ")}`,
      );

      onLaunched(accepted.run_id);
    } catch (caught) {
      setLaunchError(
        caught instanceof EvaluationApiError
          ? caught.message
          : "Could not queue the benchmark run.",
      );
    } finally {
      setIsLaunching(false);
    }
  };

  const blockingError =
    providerError ??
    (providerStatus === "ready" && selectableProviders.length === 0
      ? "No enabled LLM provider is configured. Add one before running a benchmark."
      : null);

  const hasActiveRun = activeRunCount > 0;

  // Cancelling is cooperative: the run stops after the question already in
  // flight, which on a mixed question can be several minutes. Say so rather
  // than letting the reader think the click failed.
  const handleStop = useCallback(async () => {
    if (activeRunIds.length === 0) {
      return;
    }

    setIsStopping(true);
    setStopError(null);

    try {
      await Promise.all(activeRunIds.map((id) => cancelRun(id)));
      onRefresh();
    } catch (caught) {
      setStopError(
        caught instanceof EvaluationApiError
          ? caught.message
          : "Could not request cancellation.",
      );
    } finally {
      setIsStopping(false);
    }
  }, [activeRunIds, onRefresh]);

  return (
    <div className="ev-runbar">
      <div className="ev-runbar__controls">
        <label className="ev-control">
          <span className="ev-control__label">Model Provider</span>
          <select
            className="ev-control__input"
            value={providerId}
            onChange={(event) => setProviderChoice(event.target.value)}
            disabled={selectableProviders.length === 0}
          >
            {selectableProviders.length === 0 && (
              <option value="">
                {providerStatus === "loading" ? "Loading…" : "None available"}
              </option>
            )}

            {selectableProviders.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.display_name}
                {provider.is_default ? " (default)" : ""}
              </option>
            ))}
          </select>
        </label>

        <div className="ev-control ev-control--wide">
          <span className="ev-control__label">Models (Small / Medium / Large)</span>
          <span className="ev-control__static" title={tierSummary ?? undefined}>
            {tierSummary ?? "Resolved by backend"}
          </span>
        </div>

        <label className="ev-control ev-control--medium">
          <span className="ev-control__label">Retrieval Mode</span>
          <select
            className="ev-control__input"
            value={retrievalMode}
            onChange={(event) => setRetrievalMode(event.target.value)}
          >
            {RETRIEVAL_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {retrievalLabel(mode)}
              </option>
            ))}
          </select>
        </label>

        <label className="ev-control ev-control--wide">
          <span className="ev-control__label">RAG Reranking</span>
          <select
            className="ev-control__input"
            value={pipeline}
            onChange={(event) =>
              setPipeline(event.target.value as RetrievalPipeline)
            }
          >
            {RETRIEVAL_PIPELINES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="ev-control ev-control--medium">
          <span className="ev-control__label">Index Type</span>
          <select
            className="ev-control__input"
            value={indexType}
            onChange={(event) =>
              setIndexType(event.target.value as IndexType)
            }
          >
            {INDEX_TYPES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="ev-control">
          <span className="ev-control__label">Dataset</span>
          <select
            className="ev-control__input"
            value={dataset}
            onChange={(event) => setDataset(event.target.value)}
          >
            {DATASETS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        <label className="ev-control">
          <span className="ev-control__label">Question Set</span>
          <select
            className="ev-control__input"
            value={questionSet}
            onChange={(event) =>
              setQuestionSet(event.target.value as QuestionSet)
            }
          >
            {QUESTION_SETS.map((name) => (
              <option key={name} value={name}>
                {questionSetLabel(name)}
              </option>
            ))}
          </select>
        </label>

        <label className="ev-control ev-control--narrow">
          <span className="ev-control__label">Top K</span>
          <input
            className="ev-control__input"
            type="number"
            min={1}
            max={100}
            value={topK}
            onChange={(event) => {
              // Backend bounds are ge=1, le=100; clamp rather than reject.
              const parsed = Number.parseInt(event.target.value, 10);

              setTopK(
                Number.isNaN(parsed) ? 5 : Math.min(100, Math.max(1, parsed)),
              );
            }}
          />
        </label>

      </div>

      <div className="ev-runbar__actions">
        {hasActiveRun && (
          <button
            type="button"
            className="ev-btn ev-btn--stop"
            onClick={handleStop}
            disabled={isStopping}
            title={
              activeRunCount === 1
                ? "Stop the run after the question in flight"
                : `Stop all ${activeRunCount} runs after their current question`
            }
          >
            <CircleStop size={15} />
            {isStopping ? "Stopping…" : "Stop"}
          </button>
        )}

        <button
          type="button"
          className="ev-btn ev-btn--ghost"
          onClick={handleRefresh}
          disabled={isRefreshing}
        >
          <RefreshCw size={15} />
          {isRefreshing ? "Refreshing…" : "Refresh"}
        </button>

        <button
          type="button"
          className="ev-btn ev-btn--primary"
          onClick={() => void launch()}
          disabled={isLaunching || !providerId || hasActiveRun}
          title={
            hasActiveRun
              ? `${activeRunCount} run${
                  activeRunCount === 1 ? " is" : "s are"
                } still in progress.`
              : undefined
          }
        >
          <PlayCircle size={15} />
          {isLaunching
            ? "Queuing…"
            : hasActiveRun
              ? "Run in progress"
              : "Run Benchmark"}
        </button>
      </div>

      {(blockingError || launchError || stopError) && (
        <p className="ev-runbar__message ev-runbar__message--error">
          {blockingError ?? launchError ?? stopError}
        </p>
      )}

      {!blockingError && !launchError && !stopError && hasActiveRun && (
        <p className="ev-runbar__message">
          {activeRunCount === 1
            ? "A benchmark is already running. Queuing another would compete for the same pipeline."
            : `${activeRunCount} benchmarks are already running.`}
        </p>
      )}

      {!blockingError && !launchError && !hasActiveRun && launchNotice && (
        <p className="ev-runbar__message">{launchNotice}</p>
      )}
    </div>
  );
}
