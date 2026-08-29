import type { ReactNode } from "react";
import { Database, House, Layers, LineChart } from "lucide-react";
import { Logo } from "../components/Logo";
import { clearSession, type SessionUser } from "../auth/session";
import "./AdminShell.css";

/**
 * The admin frame: a vertical rail beside whichever screen is open.
 *
 * Only admins see it. An analyst has exactly one screen — the console —
 * so a rail listing one destination would be furniture rather than
 * navigation.
 *
 * Evaluation is in the rail but leaves the frame: the dashboard carries
 * its own dense sidebar, and nesting one rail inside another gives the
 * reader two column of navigation to read before any content.
 */

export interface AdminNavItem {
  id: string;
  label: string;
  detail: string;
  icon: typeof House;
  path: string;
}

export const ADMIN_NAV: AdminNavItem[] = [
  {
    id: "home",
    label: "Home",
    detail: "Ask a question",
    icon: House,
    path: "/",
  },
  {
    id: "providers",
    label: "LLM Providers",
    detail: "Models and defaults",
    icon: Layers,
    path: "/providers",
  },
  {
    id: "ingestion",
    label: "Ingestion",
    detail: "Upload, EDGAR, corpus",
    icon: Database,
    path: "/ingestion",
  },
  {
    id: "evaluation",
    label: "Evaluation",
    detail: "Benchmarks and runs",
    icon: LineChart,
    path: "/evaluation",
  },
];

export function AdminShell({
  activeId,
  user,
  onNavigate,
  children,
}: {
  activeId: string;
  user: SessionUser;
  onNavigate: (path: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="admin">
      <nav className="admin__rail" aria-label="Sections">
        <a
          className="admin__brand"
          href="#/"
          onClick={(event) => {
            event.preventDefault();
            onNavigate("/");
          }}
        >
          <Logo size={30} />
          <span className="admin__brand-text">
            <span className="admin__brand-name">FinIntel</span>
            <span className="admin__brand-sub">AI Financial Intelligence</span>
          </span>
        </a>

        <ul className="admin__nav">
          {ADMIN_NAV.map((item) => {
            const Icon = item.icon;
            const active = item.id === activeId;

            return (
              <li key={item.id}>
                <a
                  className={`admin__item${active ? " admin__item--on" : ""}`}
                  href={`#${item.path}`}
                  aria-current={active ? "page" : undefined}
                  onClick={(event) => {
                    event.preventDefault();
                    onNavigate(item.path);
                  }}
                >
                  <Icon size={17} className="admin__icon" aria-hidden="true" />
                  <span className="admin__item-text">
                    <span className="admin__item-label">{item.label}</span>
                    <span className="admin__item-detail">{item.detail}</span>
                  </span>
                </a>
              </li>
            );
          })}
        </ul>

        <div className="admin__footer">
          <span className="admin__who">
            <span className="admin__email">{user.email}</span>
            <span className="admin__role">{user.role}</span>
          </span>

          <button
            type="button"
            className="admin__signout"
            onClick={() => {
              clearSession();
              window.location.reload();
            }}
          >
            Sign out
          </button>
        </div>
      </nav>

      <main className="admin__content">{children}</main>
    </div>
  );
}
