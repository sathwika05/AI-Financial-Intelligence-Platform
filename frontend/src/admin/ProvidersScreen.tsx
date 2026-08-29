import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, CircleSlash, KeyRound, Star } from "lucide-react";
import type { Provider } from "../evaluation/api";
import {
  AdminApiError,
  listProviderModels,
  listProviders,
  setDefaultProvider,
  toggleProvider,
  type ProviderModel,
} from "./api";
import "./AdminScreens.css";

/**
 * Provider registry, with the controls it never had.
 *
 * The evaluation dashboard listed providers read-only and told the reader
 * to "register an LLM provider through the admin API" — which meant curl.
 * The endpoints were always there.
 *
 * Creating and deleting providers is deliberately absent: a new provider
 * needs an API key, and putting a key field in a browser form makes the
 * key the page's problem. Keys stay with whoever seeds the registry.
 */
export function ProvidersScreen() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, ProviderModel[]>>({});

  const load = useCallback(async () => {
    try {
      const rows = await listProviders();

      setProviders(rows);
      setStatus("ready");
      setError(null);

      // Tiers are a separate call per provider. Failures are swallowed:
      // a provider whose models cannot be read is still configurable, and
      // the row says "not configured" rather than the page erroring.
      const pairs = await Promise.all(
        rows.map(async (row) => {
          try {
            return [row.id, await listProviderModels(row.id)] as const;
          } catch {
            return [row.id, [] as ProviderModel[]] as const;
          }
        }),
      );

      setModels(Object.fromEntries(pairs));
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not load providers.",
      );
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(id: string, action: () => Promise<Provider>) {
    setBusyId(id);
    setError(null);

    try {
      await action();
      // Re-read rather than patching in place: setting a default clears
      // it on every other provider, so one row's response does not
      // describe the table.
      await load();
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "That did not work.",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="screen">
      <header className="screen__head">
        <h1 className="screen__title">LLM Providers</h1>
        <p className="screen__lede">
          Which provider answers a query, and which model tiers it resolves
          to. Exactly one provider is the default.
        </p>
      </header>

      {error && (
        <p className="screen__error" role="alert">
          {error}
        </p>
      )}

      {status === "loading" && <p className="screen__note">Loading…</p>}

      {status === "ready" && providers.length === 0 && (
        <p className="screen__note">
          No providers registered. They are seeded with their API keys
          rather than added here.
        </p>
      )}

      {providers.length > 0 && (
        <div className="screen__table-wrap">
          <table className="screen__table">
            <thead>
              <tr>
                <th scope="col">Provider</th>
                <th scope="col">Model tiers</th>
                <th scope="col">API key</th>
                <th scope="col">Status</th>
                <th scope="col">Default</th>
                <th scope="col" className="screen__col-actions">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => {
                const busy = busyId === provider.id;

                return (
                  <tr
                    key={provider.id}
                    className={provider.is_enabled ? "" : "is-off"}
                  >
                    <td>
                      <span className="screen__name">
                        {provider.display_name}
                      </span>
                      <span className="screen__slug">{provider.name}</span>
                    </td>

                    <td>
                      <TierList models={models[provider.id]} />
                    </td>

                    <td>
                      {provider.has_api_key ? (
                        <span className="screen__pill screen__pill--ok">
                          <KeyRound size={11} /> stored
                        </span>
                      ) : (
                        <span className="screen__pill screen__pill--warn">
                          missing
                        </span>
                      )}
                    </td>

                    <td>
                      {provider.is_enabled ? (
                        <span className="screen__pill screen__pill--ok">
                          <CheckCircle2 size={11} /> enabled
                        </span>
                      ) : (
                        <span className="screen__pill">
                          <CircleSlash size={11} /> disabled
                        </span>
                      )}
                    </td>

                    <td>
                      {provider.is_default && (
                        <span className="screen__pill screen__pill--default">
                          <Star size={11} /> default
                        </span>
                      )}
                    </td>

                    <td className="screen__col-actions">
                      <button
                        type="button"
                        className="screen__btn"
                        disabled={busy}
                        onClick={() =>
                          void act(provider.id, () =>
                            toggleProvider(provider.id),
                          )
                        }
                      >
                        {provider.is_enabled ? "Disable" : "Enable"}
                      </button>

                      <button
                        type="button"
                        className="screen__btn screen__btn--primary"
                        // A disabled provider cannot be the default: the
                        // server clears default when it is disabled, so
                        // offering it here would promise a no-op.
                        disabled={
                          busy || provider.is_default || !provider.is_enabled
                        }
                        onClick={() =>
                          void act(provider.id, () =>
                            setDefaultProvider(provider.id),
                          )
                        }
                      >
                        Make default
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="screen__footnote">
        Disabling the default provider clears the default. Register new
        providers, and rotate their keys, where the keys live — not here.
      </p>
    </div>
  );
}


const TIER_ORDER = ["small", "medium", "large"];

/** The three tiers, in the order the backend resolves them. */
function TierList({ models }: { models: ProviderModel[] | undefined }) {
  if (!models || models.length === 0) {
    return <span className="screen__slug">not configured</span>;
  }

  const byTier = [...models].sort(
    (a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier),
  );

  return (
    <span className="screen__tiers">
      {byTier.map((model) => (
        <span key={model.id} className="screen__tier">
          <span className="screen__tier-name">{model.tier}</span>
          <span className="screen__tier-model">{model.model_name}</span>
        </span>
      ))}
    </span>
  );
}
