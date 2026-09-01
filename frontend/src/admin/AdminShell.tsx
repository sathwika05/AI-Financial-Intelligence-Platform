import { useEffect, useState, type ReactNode } from "react";
import {
  Database,
  ExternalLink as ExternalLinkIcon,
  House,
  Layers,
  LineChart,
  ScrollText,
  Waypoints,
} from "lucide-react";
import { Logo } from "../components/Logo";
import { clearSession, type SessionUser } from "../auth/session";
import { fetchExternalLinks, type ExternalLinks } from "./api";
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
    label: "Ingestion & Indexing",
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
          href="/"
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
                  href={item.path}
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
          <ExternalRail />
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

/**
 * The two tools that explain a run after it has finished.
 *
 * They sit in the same list as the rest of the navigation, so the rail
 * reads as one set of destinations. What marks them out is the arrow on
 * the right: they open a third-party console in a new tab rather than
 * swapping the screen beside the rail.
 *
 * Rendered even when unconfigured, disabled, with the server's own
 * explanation on hover. Hiding them would be tidier on a laptop and worse
 * everywhere else: the person wondering why there is no CloudWatch link
 * is exactly the person who needs to be told which variable to set.
 */
function ExternalRail() {
  const [links, setLinks] = useState<ExternalLinks | null>(null);

  useEffect(() => {
    let live = true;

    fetchExternalLinks()
      .then((loaded) => {
        if (live) setLinks(loaded);
      })
      // A failure here must not take the rail down with it. The links are
      // a convenience; navigation is not.
      .catch(() => undefined);

    return () => {
      live = false;
    };
  }, []);

  if (!links) return null;

  const items = [
    { id: "cloudwatch", label: "CloudWatch Logs", detail: "What the containers printed", icon: ScrollText, link: links.cloudwatch },
    { id: "langsmith", label: "LangSmith", detail: "Traces for each run", icon: Waypoints, link: links.langsmith },
  ];

  return (
    <>
      {items.map(({ id, label, detail, icon: Icon, link }) => (
        <li key={id}>
          {link.configured && link.url ? (
            <a
              className="admin__item admin__item--external"
              href={link.url}
              target="_blank"
              // noopener because the opened page gets a handle on this
              // window otherwise, and it is a third-party console.
              rel="noreferrer noopener"
            >
              <Icon size={17} className="admin__icon" aria-hidden="true" />
              <span className="admin__item-text">
                <span className="admin__item-label">{label}</span>
                <span className="admin__item-detail">{detail}</span>
              </span>
              <ExternalLinkIcon
                size={12}
                className="admin__item-out"
                aria-hidden="true"
              />
            </a>
          ) : (
            <span
              className="admin__item admin__item--off"
              title={link.detail ?? undefined}
              aria-disabled="true"
            >
              <Icon size={17} className="admin__icon" aria-hidden="true" />
              <span className="admin__item-text">
                <span className="admin__item-label">{label}</span>
                <span className="admin__item-detail">Not configured</span>
              </span>
            </span>
          )}
        </li>
      ))}
    </>
  );
}
