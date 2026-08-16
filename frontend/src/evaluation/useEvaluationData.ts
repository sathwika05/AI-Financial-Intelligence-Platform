import { useCallback, useEffect, useState } from "react";
import {
  EvaluationApiError,
  listProviderModels,
  listProviders,
  listRuns,
  type Provider,
  type ProviderModel,
  type RunMetrics,
} from "./api";
import { isTerminal } from "./metrics";

export type LoadStatus = "idle" | "loading" | "ready" | "error";

function messageFor(caught: unknown, fallback: string): string {
  return caught instanceof EvaluationApiError ? caught.message : fallback;
}

function isAbort(caught: unknown): boolean {
  return caught instanceof DOMException && caught.name === "AbortError";
}

const RUN_HISTORY_LIMIT = 50;

/** How often an in-flight benchmark is re-polled. A run takes minutes, so
 *  anything faster only adds request noise. */
const POLL_INTERVAL_MS = 5000;

export interface RunsState {
  runs: RunMetrics[];
  status: LoadStatus;
  error: string | null;
  /** True while refetching in the background, with stale data still shown. */
  isRefreshing: boolean;
  reload: () => void;
}

export function useRuns(): RunsState {
  const [runs, setRuns] = useState<RunMetrics[]>([]);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Bumping the token is what re-runs the fetch, which keeps the effect free
  // of any synchronous state write of its own.
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    listRuns(RUN_HISTORY_LIMIT, controller.signal)
      .then((result) => {
        if (cancelled) {
          return;
        }

        setRuns(result);
        setError(null);
        setStatus("ready");
        setIsRefreshing(false);
      })
      .catch((caught: unknown) => {
        if (cancelled || isAbort(caught)) {
          return;
        }

        setError(messageFor(caught, "Could not load benchmark runs."));
        setIsRefreshing(false);

        // A failed refresh keeps the last good table on screen; a failed
        // first load has nothing to fall back to.
        setStatus((current) => (current === "ready" ? "ready" : "error"));
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [reloadToken]);

  const reload = useCallback(() => {
    setIsRefreshing(true);
    setReloadToken((token) => token + 1);
  }, []);

  return { runs, status, error, isRefreshing, reload };
}

/**
 * Re-reads the run list on an interval while any run is still queued or
 * running, and stops as soon as everything has reached a terminal state.
 */
export function useRunPolling(runs: RunMetrics[], reload: () => void): boolean {
  const hasActiveRun = runs.some((run) => !isTerminal(run.status));

  useEffect(() => {
    if (!hasActiveRun) {
      return;
    }

    const timer = window.setInterval(reload, POLL_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [hasActiveRun, reload]);

  return hasActiveRun;
}

export interface ProvidersState {
  providers: Provider[];
  status: LoadStatus;
  error: string | null;
}

export function useProviders(): ProvidersState {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    listProviders(controller.signal)
      .then((result) => {
        setProviders(result);
        setStatus("ready");
      })
      .catch((caught: unknown) => {
        if (isAbort(caught)) {
          return;
        }

        setError(messageFor(caught, "Could not load LLM providers."));
        setStatus("error");
      });

    return () => controller.abort();
  }, []);

  return { providers, status, error };
}

interface ModelsState {
  /** Which provider the loaded models belong to. */
  providerId: string | null;
  models: ProviderModel[];
  status: LoadStatus;
}

/**
 * Tier models for one provider.
 *
 * The loaded provider id is stored alongside the models so that switching the
 * selector reports "loading" rather than briefly showing the previous
 * provider's tiers as if they were the new one's.
 */
export function useProviderModels(providerId: string | null): {
  models: ProviderModel[];
  status: LoadStatus;
} {
  const [state, setState] = useState<ModelsState>({
    providerId: null,
    models: [],
    status: "idle",
  });

  useEffect(() => {
    if (!providerId) {
      return;
    }

    const controller = new AbortController();

    listProviderModels(providerId, controller.signal)
      .then((result) =>
        setState({ providerId, models: result, status: "ready" }),
      )
      .catch((caught: unknown) => {
        if (isAbort(caught)) {
          return;
        }

        setState({ providerId, models: [], status: "error" });
      });

    return () => controller.abort();
  }, [providerId]);

  if (!providerId) {
    return { models: [], status: "idle" };
  }

  if (state.providerId !== providerId) {
    return { models: [], status: "loading" };
  }

  return { models: state.models, status: state.status };
}
