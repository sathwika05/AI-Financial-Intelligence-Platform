import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import {
  Activity,
  BarChart3,
  BrainCircuit,
  CirclePlus,
  Database,
  ExternalLink,
  FileText,
  Gauge,
  Home,
  Layers3,
  Search,
  Settings,
  Sparkles,
  Target,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";

/**
 * Dashboard navigation.
 *
 * The sections and their order follow the design reference exactly, and
 * every entry is backed by real data. Per-Question Results was the one that
 * was not, until results were persisted per question rather than only as a
 * run-level aggregate.
 *
 * There is no link back to the research console here, because the reference
 * has none. The brand mark serves that purpose.
 */

type IconComponent = ComponentType<{ size?: number; className?: string }>;

export interface NavItem {
  id: string;
  label: string;
  icon: IconComponent;
  /** Renders as an outbound link with a ↗ marker instead of a view route. */
  href?: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [
      { id: "summary", label: "Summary", icon: Home },
      { id: "runs", label: "Runs", icon: Layers3 },
      { id: "compare", label: "Compare Runs", icon: CirclePlus },
    ],
  },
  {
    title: "Data Management",
    items: [
      { id: "datasets", label: "Datasets", icon: Database },
      { id: "question-sets", label: "Question Sets", icon: FileText },
    ],
  },
  {
    title: "Evaluation",
    items: [
      { id: "metrics", label: "Metrics", icon: Sparkles },
      { id: "retrieval-modes", label: "Retrieval Modes", icon: Search },
      { id: "providers", label: "Models (Providers)", icon: BrainCircuit },
      { id: "errors", label: "Error Analysis", icon: TriangleAlert },
      { id: "trends", label: "Trend Analysis", icon: TrendingUp },
    ],
  },
  {
    title: "Analytics",
    items: [
      { id: "per-question", label: "Per-Question Results", icon: Target },
      { id: "models", label: "Model Comparison", icon: BarChart3 },
      { id: "retrieval", label: "Retrieval Comparison", icon: Activity },
    ],
  },
  {
    title: "System",
    items: [
      {
        id: "observability",
        label: "Observability (LangSmith)",
        icon: Gauge,
        // The backend traces to LangSmith, but no endpoint reports which
        // workspace or project, so this opens LangSmith rather than a
        // deep link that might point at the wrong project.
        href: "https://smith.langchain.com/",
      },
      { id: "settings", label: "Settings", icon: Settings },
    ],
  },
];

export const DEFAULT_VIEW = "summary";

const VALID_VIEWS = new Set(
  NAV_SECTIONS.flatMap((section) => section.items)
    .filter((item) => !item.href)
    .map((item) => item.id),
);

export function isValidView(view: string): boolean {
  return VALID_VIEWS.has(view);
}

interface HealthReport {
  status: string;
  db: string;
  redis: string;
}

/** Polls GET /health so the footer reflects the backend, not just the UI. */
function useHealth(): { report: HealthReport | null; reachable: boolean } {
  const [report, setReport] = useState<HealthReport | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const response = await fetch("/health");

        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }

        const body = (await response.json()) as HealthReport;

        if (!cancelled) {
          setReport(body);
          setReachable(true);
        }
      } catch {
        if (!cancelled) {
          setReachable(false);
        }
      }
    };

    void check();

    const timer = window.setInterval(() => void check(), 60_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return { report, reachable };
}

export function Sidebar({
  activeView,
  onNavigate,
}: {
  activeView: string;
  onNavigate: (view: string) => void;
}) {
  const { report, reachable } = useHealth();

  const degraded =
    !reachable ||
    !report ||
    report.db !== "connected" ||
    report.redis !== "connected";

  const healthLabel = !reachable
    ? "Backend Unreachable"
    : degraded
      ? "Degraded Services"
      : "All Systems Operational";

  const healthDetail = !reachable
    ? "No response from the API"
    : report
      ? `db ${report.db.split(":")[0]} · redis ${report.redis.split(":")[0]}`
      : "checking…";

  return (
    <nav className="ev-sidebar" aria-label="Evaluation sections">
      <a className="ev-brand" href="#/">
        <span className="ev-brand__mark" aria-hidden="true">
          <Sparkles size={19} />
        </span>

        <span className="ev-brand__text">
          <span className="ev-brand__title">Financial Intelligence</span>
          <span className="ev-brand__subtitle">AI Evaluation Dashboard</span>
        </span>
      </a>

      <div className="ev-sidebar__scroll">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="ev-navgroup">
            <p className="ev-navgroup__title">{section.title}</p>

            <ul className="ev-navgroup__list">
              {section.items.map((item) =>
                item.href ? (
                  <li key={item.id}>
                    <a
                      className="ev-navitem"
                      href={item.href}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      <item.icon size={16} className="ev-navitem__icon" />
                      <span>{item.label}</span>
                      <ExternalLink size={11} className="ev-navitem__out" />
                    </a>
                  </li>
                ) : (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`ev-navitem${
                        item.id === activeView ? " ev-navitem--active" : ""
                      }`}
                      aria-current={item.id === activeView ? "page" : undefined}
                      onClick={() => onNavigate(item.id)}
                    >
                      <item.icon size={16} className="ev-navitem__icon" />
                      <span>{item.label}</span>
                    </button>
                  </li>
                ),
              )}
            </ul>
          </div>
        ))}
      </div>

      <div
        className={`ev-health${degraded ? " ev-health--degraded" : ""}`}
        role="status"
      >
        <span className="ev-health__label">
          <span className="ev-health__dot" aria-hidden="true" />
          {healthLabel}
        </span>
        <span className="ev-health__detail">{healthDetail}</span>
      </div>
    </nav>
  );
}
