import { useMemo, useState } from "react";
import type { RankedCompany } from "../api/types";
import {
  formatGrowth,
  formatMarketCap,
  formatRatio,
  formatScore,
  toNumber,
} from "../lib/format";
import { companyKey } from "../lib/companies";
import { factorLabel, FACTOR_ORDER } from "../lib/labels";
import "./ComparisonTable.css";

type SortDirection = "asc" | "desc";

interface ColumnDef {
  id: string;
  label: string;
  numeric: boolean;
  /** Sort key; null values always sort last regardless of direction. */
  sortValue: (company: RankedCompany) => number | string | null;
  render: (company: RankedCompany) => string;
}

const FACTOR_COLUMNS: ColumnDef[] = FACTOR_ORDER.map((factor) => ({
  id: `score-${factor}`,
  label: factorLabel(factor),
  numeric: true,
  sortValue: (company) => company.scores?.[factor] ?? null,
  render: (company) => formatScore(company.scores?.[factor]),
}));

const COLUMNS: ColumnDef[] = [
  {
    id: "rank",
    label: "Rank",
    numeric: true,
    sortValue: (company) => company.rank ?? null,
    render: (company) => (company.rank == null ? "—" : String(company.rank)),
  },
  {
    id: "company",
    label: "Company",
    numeric: false,
    sortValue: (company) => company.name?.toLowerCase() ?? null,
    render: (company) => company.name ?? "Unknown",
  },
  {
    id: "ticker",
    label: "Ticker",
    numeric: false,
    sortValue: (company) => company.ticker?.toUpperCase() ?? null,
    render: (company) => company.ticker ?? "—",
  },
  {
    id: "final_score",
    label: "Overall",
    numeric: true,
    sortValue: (company) => company.final_score ?? null,
    render: (company) => formatScore(company.final_score),
  },
  {
    id: "pe",
    label: "P/E",
    numeric: true,
    sortValue: (company) => toNumber(company.metrics?.pe_ratio),
    render: (company) => formatRatio(company.metrics?.pe_ratio),
  },
  {
    id: "growth",
    label: "Revenue Growth",
    numeric: true,
    sortValue: (company) => toNumber(company.metrics?.revenue_growth),
    render: (company) => formatGrowth(company.metrics?.revenue_growth),
  },
  {
    id: "eps",
    label: "EPS",
    numeric: true,
    sortValue: (company) => toNumber(company.metrics?.eps),
    render: (company) => formatRatio(company.metrics?.eps),
  },
  {
    id: "market_cap",
    label: "Market Cap",
    numeric: true,
    sortValue: (company) => toNumber(company.metrics?.market_cap),
    render: (company) => formatMarketCap(company.metrics?.market_cap),
  },
  ...FACTOR_COLUMNS,
];

function compare(
  a: number | string | null,
  b: number | string | null,
  direction: SortDirection,
): number {
  // Missing values sink to the bottom in both directions.
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;

  const result =
    typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b));

  return direction === "asc" ? result : -result;
}

export function ComparisonTable({
  companies,
  onOpenDetails,
}: {
  companies: RankedCompany[];
  onOpenDetails: (company: RankedCompany) => void;
}) {
  // null = backend ranking order, which is the meaningful default.
  const [sort, setSort] = useState<{
    columnId: string;
    direction: SortDirection;
  } | null>(null);

  const rows = useMemo(() => {
    if (!sort) {
      return companies;
    }

    const column = COLUMNS.find((item) => item.id === sort.columnId);

    if (!column) {
      return companies;
    }

    return [...companies].sort((a, b) =>
      compare(column.sortValue(a), column.sortValue(b), sort.direction),
    );
  }, [companies, sort]);

  function toggleSort(columnId: string) {
    setSort((current) => {
      if (!current || current.columnId !== columnId) {
        return { columnId, direction: "desc" };
      }

      if (current.direction === "desc") {
        return { columnId, direction: "asc" };
      }

      return null;
    });
  }

  if (companies.length === 0) {
    return (
      <p className="comparison__empty">
        No comparable companies were returned for this question.
      </p>
    );
  }

  return (
    <div className="comparison">
      <div className="comparison__scroll">
        <table className="comparison__table">
          <thead>
            <tr>
              {COLUMNS.map((column) => {
                const active = sort?.columnId === column.id;

                return (
                  <th
                    key={column.id}
                    scope="col"
                    className={column.numeric ? "is-numeric" : undefined}
                    aria-sort={
                      active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      className={`comparison__sort${
                        active ? " comparison__sort--active" : ""
                      }`}
                      onClick={() => toggleSort(column.id)}
                    >
                      {column.label}
                      <span className="comparison__caret" aria-hidden="true">
                        {active ? (sort.direction === "asc" ? "↑" : "↓") : "↕"}
                      </span>
                    </button>
                  </th>
                );
              })}
              <th scope="col" className="comparison__action-head">
                <span className="visually-hidden">Details</span>
              </th>
            </tr>
          </thead>

          <tbody>
            {rows.map((company, index) => (
              <tr key={companyKey(company, index)}>
                {COLUMNS.map((column) => {
                  const value = column.render(company);

                  return (
                    <td
                      key={column.id}
                      className={[
                        column.numeric ? "is-numeric num" : "",
                        value === "N/A" ? "is-absent" : "",
                        column.id === "company" ? "is-primary" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {value}
                    </td>
                  );
                })}
                <td className="comparison__action-cell">
                  <button
                    type="button"
                    className="comparison__details"
                    onClick={() => onOpenDetails(company)}
                  >
                    Details
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="comparison__hint">
        {sort
          ? "Sorted by column. Select the active column twice more to restore ranking order."
          : "Ordered by the ranking returned for this question. Select a column to sort."}
      </p>
    </div>
  );
}
