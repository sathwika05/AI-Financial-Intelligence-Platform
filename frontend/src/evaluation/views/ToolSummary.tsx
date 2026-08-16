import { Wrench } from "lucide-react";
import { formatPercent } from "../format";
import { Panel } from "../components/primitives";

/**
 * Tool execution summary.
 *
 * The design reference shows a success rate and an average latency per tool.
 * Neither exists: the pipeline times a question end to end rather than each
 * tool, and records no per-tool outcome. What it does record is which tools
 * each question invoked and which its golden entry expected, so the columns
 * here are the ones those two facts genuinely support.
 */

/** Display names for the tool ids `plan_to_tools` emits. */
const TOOL_LABEL: Record<string, string> = {
  planner: "Planner",
  sql: "SQL Executor",
  vector: "Vector Retriever",
  market: "Market API",
};

/** Planner first, then the retrieval channels in pipeline order. */
const TOOL_ORDER = ["planner", "sql", "vector", "market"];

function toolRank(tool: string): number {
  const index = TOOL_ORDER.indexOf(tool);

  return index === -1 ? TOOL_ORDER.length : index;
}

export function ToolSummaryPanel({
  summary,
  span = 3,
}: {
  summary: Record<string, Record<string, number | null | undefined>>;
  span?: number;
}) {
  const tools = Object.keys(summary).sort(
    (a, b) => toolRank(a) - toolRank(b) || a.localeCompare(b),
  );

  return (
    <Panel
      title="Tool Execution Summary"
      note={`${tools.length} tools`}
      icon={Wrench}
      tone="green"
      span={span}
    >
      {tools.length === 0 ? (
        <p className="ev-note">No tool invocations recorded for this run.</p>
      ) : (
        <div className="ev-tablewrap">
          <table className="ev-table">
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col" className="ev-table__num">
                  Calls
                </th>
                <th scope="col" className="ev-table__num">
                  Expected
                </th>
                <th scope="col" className="ev-table__num">
                  Recall
                </th>
                <th scope="col" className="ev-table__num">
                  Precision
                </th>
              </tr>
            </thead>

            <tbody>
              {tools.map((tool) => {
                const row = summary[tool];
                const recall = row.recall;
                const precision = row.precision;

                return (
                  <tr key={tool}>
                    <td>{TOOL_LABEL[tool] ?? tool}</td>
                    <td className="ev-table__num">{row.calls ?? 0}</td>
                    <td className="ev-table__num">{row.expected ?? 0}</td>
                    <td
                      className={`ev-table__num${
                        typeof recall === "number" && recall === 1
                          ? " ev-table__good"
                          : ""
                      }`}
                    >
                      {typeof recall === "number"
                        ? formatPercent(recall, 0)
                        : "—"}
                    </td>
                    <td
                      className={`ev-table__num${
                        typeof precision === "number" && precision === 1
                          ? " ev-table__good"
                          : ""
                      }`}
                    >
                      {typeof precision === "number"
                        ? formatPercent(precision, 0)
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="ev-note" style={{ marginTop: 8 }}>
        Recall is how often an expected tool was invoked; precision how often
        an invoked tool was expected. Per-tool latency and success are not
        recorded.
      </p>
    </Panel>
  );
}
