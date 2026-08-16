import { useMemo, useState } from "react";
import { PlayCircle, RefreshCw } from "lucide-react";
import {
  DATASETS,
  EvaluationApiError,
  QUESTION_SETS,
  RETRIEVAL_MODES,
  triggerRun,
  type QuestionSet,
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
}: {
  onLaunched: (runId: string) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const { providers, status: providerStatus, error: providerError } =
    useProviders();

  // Null means "no explicit choice yet", which resolves to the provider's own
  // default below. Deriving rather than seeding avoids a render pass where
  // the selector is blank.
  const [providerChoice, setProviderChoice] = useState<string | null>(null);
  const [dataset, setDataset] = useState<string>(DATASETS[0]);
  const [retrievalMode, setRetrievalMode] = useState<string>(
    RETRIEVAL_MODES[0],
  );
  const [questionSet, setQuestionSet] = useState<QuestionSet>(
    QUESTION_SETS[0],
  );
  const [topK, setTopK] = useState(5);

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
        <button
          type="button"
          className="ev-btn ev-btn--ghost"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          <RefreshCw size={15} />
          {isRefreshing ? "Refreshing…" : "Refresh"}
        </button>

        <button
          type="button"
          className="ev-btn ev-btn--primary"
          onClick={() => void launch()}
          disabled={isLaunching || !providerId}
        >
          <PlayCircle size={15} />
          {isLaunching ? "Queuing…" : "Run Benchmark"}
        </button>
      </div>

      {(blockingError || launchError) && (
        <p className="ev-runbar__message ev-runbar__message--error">
          {blockingError ?? launchError}
        </p>
      )}

      {!blockingError && !launchError && launchNotice && (
        <p className="ev-runbar__message">{launchNotice}</p>
      )}
    </div>
  );
}
