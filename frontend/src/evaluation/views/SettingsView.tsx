import { useEffect, useState } from "react";
import { BrainCircuit, Gauge, Settings as SettingsIcon } from "lucide-react";
import {
  DATASETS,
  QUESTION_SETS,
  RETRIEVAL_MODES,
  type RunMetrics,
} from "../api";
import {
  formatDateTime,
  questionSetLabel,
  retrievalLabel,
  titleCase,
} from "../format";
import { useProviders } from "../useEvaluationData";
import { Field, Panel, StatusPill } from "../components/primitives";
import { navigateTo } from "../../lib/router";

/**
 * Runtime configuration, read-only.
 *
 * Nothing here is editable: the benchmark's options come from the backend's
 * own constants and provider registry, and changing a provider means handling
 * an API key, which belongs in the admin API rather than a results dashboard.
 */

interface HealthReport {
  status: string;
  db: string;
  redis: string;
}

function useHealthOnce(): HealthReport | null {
  const [report, setReport] = useState<HealthReport | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetch("/health")
      .then((response) => (response.ok ? response.json() : null))
      .then((body: HealthReport | null) => {
        if (!cancelled) {
          setReport(body);
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, []);

  return report;
}

export function SettingsView({ runs }: { runs: RunMetrics[] }) {
  const { providers } = useProviders();
  const health = useHealthOnce();

  const latest = runs[0];
  const enabled = providers.filter((provider) => provider.is_enabled);
  const defaultProvider = providers.find((provider) => provider.is_default);

  return (
    <div className="ev-grid">
      <Panel
        title="Services"
        note="Live"
        icon={Gauge}
        tone="green"
        span={4}
      >
        <div className="ev-runhead__facts" style={{ marginTop: 0, borderTop: 0, paddingTop: 0 }}>
          <Field
            label="API"
            value={<StatusPill status={health ? "connected" : "error"} />}
          />
          <Field
            label="Database"
            value={
              <StatusPill
                status={health?.db === "connected" ? "connected" : "error"}
              />
            }
          />
          <Field
            label="Redis"
            value={
              <StatusPill
                status={health?.redis === "connected" ? "connected" : "error"}
              />
            }
          />
        </div>
      </Panel>

      <Panel
        title="Providers"
        note={`${enabled.length} of ${providers.length} enabled`}
        icon={BrainCircuit}
        tone="violet"
        span={4}
        link={{
          label: "View Models (Providers)",
          onClick: () => {
            navigateTo("/evaluation/providers");
          },
        }}
      >
        <div className="ev-runhead__facts" style={{ marginTop: 0, borderTop: 0, paddingTop: 0 }}>
          <Field label="Default" value={defaultProvider?.display_name} />
          <Field
            label="Last tested"
            value={formatDateTime(defaultProvider?.last_tested_at)}
          />
          <Field
            label="Key"
            value={defaultProvider?.has_api_key ? "configured" : "missing"}
          />
        </div>
      </Panel>

      <Panel
        title="Last Run Configuration"
        note="Most recent"
        icon={SettingsIcon}
        tone="amber"
        span={4}
      >
        {latest ? (
          <div className="ev-runhead__facts" style={{ marginTop: 0, borderTop: 0, paddingTop: 0 }}>
            <Field label="Dataset" value={latest.dataset} />
            <Field
              label="Retrieval"
              value={retrievalLabel(latest.retrieval_mode)}
            />
            <Field
              label="Question set"
              value={questionSetLabel(latest.question_set)}
            />
            <Field
              label="Top K"
              value={latest.k == null ? null : String(latest.k)}
            />
          </div>
        ) : (
          <p className="ev-note">No runs recorded yet.</p>
        )}
      </Panel>

      <Panel
        title="Benchmark Options"
        note="Accepted by the API"
        icon={SettingsIcon}
        tone="blue"
        span={12}
      >
        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">Option</th>
                <th scope="col">Accepted values</th>
                <th scope="col">Set by</th>
              </tr>
            </thead>

            <tbody>
              <tr>
                <td>Question set</td>
                <td>{QUESTION_SETS.map(titleCase).join(", ")}</td>
                <td className="ev-table__muted">
                  Fixed list validated by the API
                </td>
              </tr>
              <tr>
                <td>Retrieval mode</td>
                <td>{RETRIEVAL_MODES.map(retrievalLabel).join(", ")}</td>
                <td className="ev-table__muted">Retrieval layer</td>
              </tr>
              <tr>
                <td>Dataset</td>
                <td>{DATASETS.join(", ")}</td>
                <td className="ev-table__muted">Ingested corpora</td>
              </tr>
              <tr>
                <td>Top K</td>
                <td>1 – 100 (default 5)</td>
                <td className="ev-table__muted">Bounded by the API</td>
              </tr>
              <tr>
                <td>Models</td>
                <td>
                  Resolved from the selected provider's small / medium / large
                  tiers
                </td>
                <td className="ev-table__muted">
                  Backend, not selectable per run
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
