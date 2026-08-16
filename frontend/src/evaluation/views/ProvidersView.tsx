import type { Provider } from "../api";
import { formatDateTime } from "../format";
import { useProviderModels, useProviders } from "../useEvaluationData";
import { BrainCircuit } from "lucide-react";
import { EmptyState, Panel, StatusPill } from "../components/primitives";

/**
 * The LLM provider registry, read-only.
 *
 * The admin endpoints support writes, but creating or editing a provider
 * means handling an API key, and this dashboard is a read surface for
 * benchmark results. Configuration stays where it already lives.
 */

const TIER_ORDER = ["small", "medium", "large"];

function ProviderCard({ provider }: { provider: Provider }) {
  const { models, status } = useProviderModels(provider.id);

  const ordered = [...models].sort(
    (a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier),
  );

  return (
    <article className="ev-provider">
      <header className="ev-provider__head">
        <div>
          <h3 className="ev-provider__name">{provider.display_name}</h3>
          <p className="ev-provider__meta num">{provider.name}</p>
        </div>

        <div className="ev-provider__flags">
          {provider.is_default && (
            <span className="ev-tag ev-tag--accent">default</span>
          )}
          <span className={`ev-tag${provider.is_enabled ? " ev-tag--ok" : ""}`}>
            {provider.is_enabled ? "enabled" : "disabled"}
          </span>
          <span className={`ev-tag${provider.has_api_key ? " ev-tag--ok" : " ev-tag--warn"}`}>
            {provider.has_api_key ? "key set" : "no key"}
          </span>
        </div>
      </header>

      <div className="ev-provider__facts">
        <span>
          Connection:{" "}
          <StatusPill status={provider.connection_status ?? "unknown"} />
        </span>
        <span className="ev-provider__tested">
          Last tested {formatDateTime(provider.last_tested_at)}
        </span>
      </div>

      {status === "loading" && <p className="ev-note">Loading models…</p>}

      {status === "error" && (
        <p className="ev-note">Could not load this provider's models.</p>
      )}

      {status === "ready" &&
        (ordered.length === 0 ? (
          <p className="ev-note">
            No model tiers configured. A benchmark on this provider will fail
            to resolve a runtime.
          </p>
        ) : (
          <div className="ev-tablewrap">
            <table className="ev-table">
              <thead>
                <tr>
                  <th scope="col">Tier</th>
                  <th scope="col">Model</th>
                  <th scope="col" className="ev-table__num">
                    In $/M
                  </th>
                  <th scope="col" className="ev-table__num">
                    Out $/M
                  </th>
                  <th scope="col">State</th>
                </tr>
              </thead>

              <tbody>
                {ordered.map((model) => (
                  <tr key={model.id}>
                    <td>{model.tier}</td>
                    <td className="num">{model.model_name}</td>
                    <td className="ev-table__num num">
                      {Number(model.input_cost_per_million).toFixed(2)}
                    </td>
                    <td className="ev-table__num num">
                      {Number(model.output_cost_per_million).toFixed(2)}
                    </td>
                    <td className="ev-table__muted">
                      {model.is_enabled ? "enabled" : "disabled"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </article>
  );
}

export function ProvidersView() {
  const { providers, status, error } = useProviders();

  if (status === "loading") {
    return <p className="ev-note">Loading providers…</p>;
  }

  if (status === "error") {
    return (
      <EmptyState
        title="Could not load providers"
        detail={error ?? "The provider registry did not respond."}
      />
    );
  }

  if (providers.length === 0) {
    return (
      <EmptyState
        title="No providers configured"
        detail="Register an LLM provider through the admin API before running a benchmark."
      />
    );
  }

  return (
    <div className="ev-grid">
      <Panel
        title="LLM Providers"
        note={`${providers.length} registered`}
        icon={BrainCircuit}
        tone="violet"
        span={12}
      >
        <div className="ev-providers">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} />
          ))}
        </div>
      </Panel>
    </div>
  );
}
