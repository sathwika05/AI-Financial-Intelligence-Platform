import { useState } from "react";
import type { RunMetrics } from "../api";
import {
  formatDateTime,
  parseModelSnapshot,
  questionSetLabel,
  retrievalLabel,
  shortRunId,
} from "../format";
import {
  PANELS,
  computeDelta,
  formatDelta,
  formatMetric,
  getSpec,
  readMetric,
} from "../metrics";
import { CirclePlus, GitCompareArrows } from "lucide-react";
import { EmptyState, Field, Panel } from "../components/primitives";

/**
 * Two runs side by side.
 *
 * The delta column is oriented by each metric's preferred direction, so green
 * always means "B is better than A" regardless of whether the underlying
 * number went up or down.
 */

function RunPicker({
  label,
  runs,
  value,
  onChange,
}: {
  label: string;
  runs: RunMetrics[];
  value: string;
  onChange: (runId: string) => void;
}) {
  return (
    <label className="ev-control">
      <span className="ev-control__label">{label}</span>
      <select
        className="ev-control__input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {shortRunId(run.run_id)} · {questionSetLabel(run.question_set)} ·{" "}
            {formatDateTime(run.created_at)}
          </option>
        ))}
      </select>
    </label>
  );
}

function RunFacts({ run }: { run: RunMetrics }) {
  return (
    <>
      <div className="ev-compare__facts">
        <Field label="Provider" value={run.provider_name} />
        <Field label="Dataset" value={run.dataset} />
        <Field label="Retrieval" value={retrievalLabel(run.retrieval_mode)} />
        <Field
          label="Question Set"
          value={questionSetLabel(run.question_set)}
        />
      </div>

      {/* Chips rather than a Field: the raw snapshot string is long enough to
          wrap mid-model-name in a narrow column. */}
      <div className="ev-runhead__models">
        {parseModelSnapshot(run.model).map((tier) => (
          <span key={tier.tier} className="ev-tier">
            <span className="ev-tier__name">{tier.tier}</span>
            <span className="ev-tier__model num">{tier.model}</span>
          </span>
        ))}
      </div>
    </>
  );
}

export function CompareView({ runs }: { runs: RunMetrics[] }) {
  const comparable = runs.filter((run) => run.status === "completed");

  const [baselineChoice, setBaselineChoice] = useState<string | null>(null);
  const [candidateChoice, setCandidateChoice] = useState<string | null>(null);

  // Defaults are derived, not seeded: the two most recent completed runs,
  // newest as the candidate. A choice pointing at a run that has since fallen
  // out of the history window falls back to the same default.
  const resolve = (choice: string | null, fallbackIndex: number): string =>
    comparable.find((run) => run.run_id === choice)?.run_id ??
    comparable[fallbackIndex]?.run_id ??
    "";

  const baselineId = resolve(baselineChoice, 1);
  const candidateId = resolve(candidateChoice, 0);

  if (comparable.length < 2) {
    return (
      <EmptyState
        title="Two completed runs are needed"
        detail={`Only ${comparable.length} completed run is recorded. Queue another benchmark to compare against it.`}
      />
    );
  }

  const baseline = comparable.find((run) => run.run_id === baselineId);
  const candidate = comparable.find((run) => run.run_id === candidateId);

  if (!baseline || !candidate) {
    return null;
  }

  return (
    <div className="ev-grid">
      <Panel
        title="Compare Runs"
        note="A vs B"
        icon={CirclePlus}
        tone="violet"
        span={12}
      >
        <div className="ev-compare__pickers">
          <RunPicker
            label="Baseline (A)"
            runs={comparable}
            value={baselineId}
            onChange={setBaselineChoice}
          />
          <RunPicker
            label="Candidate (B)"
            runs={comparable}
            value={candidateId}
            onChange={setCandidateChoice}
          />
        </div>

        <div className="ev-compare__columns">
          <div>
            <p className="ev-compare__heading">A · {shortRunId(baseline.run_id)}</p>
            <RunFacts run={baseline} />
          </div>
          <div>
            <p className="ev-compare__heading">
              B · {shortRunId(candidate.run_id)}
            </p>
            <RunFacts run={candidate} />
          </div>
        </div>
      </Panel>

      <Panel
        title="Metric Differences"
        note="B relative to A"
        icon={GitCompareArrows}
        tone="blue"
        span={12}
      >
        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col" className="ev-table__num">
                  A
                </th>
                <th scope="col" className="ev-table__num">
                  B
                </th>
                <th scope="col" className="ev-table__num">
                  Change
                </th>
              </tr>
            </thead>

            <tbody>
              {PANELS.flatMap((panel) =>
                panel.keys.map((key) => {
                  const a = readMetric(baseline, key);
                  const b = readMetric(candidate, key);
                  const delta = computeDelta(key, b, a);

                  const tone =
                    !delta || delta.improved == null
                      ? "flat"
                      : delta.improved
                        ? "up"
                        : "down";

                  return (
                    <tr key={`${panel.id}-${key}`}>
                      <td title={getSpec(key).hint}>{getSpec(key).label}</td>
                      <td className="ev-table__num num">
                        {formatMetric(key, a)}
                      </td>
                      <td className="ev-table__num num">
                        {formatMetric(key, b)}
                      </td>
                      <td className="ev-table__num">
                        {delta && delta.change !== 0 ? (
                          <span className={`ev-delta ev-delta--${tone}`}>
                            <span className="num">
                              {formatDelta(key, delta.change)}
                            </span>
                          </span>
                        ) : (
                          <span className="ev-table__muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
