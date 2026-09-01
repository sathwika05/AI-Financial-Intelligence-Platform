import type React from "react";
import { useCallback, useEffect, useState } from "react";

/**
 * Path routing, hand-rolled.
 *
 * The app has a handful of screens, so a router dependency would cost more
 * than it returns.
 *
 * This used hash fragments, on the reasoning that the bundle might be opened
 * off the filesystem or served behind a path prefix -- neither of which is
 * true now. FastAPI serves the app and answers any unknown path with
 * index.html, so a real URL survives a refresh, a bookmark and a shared
 * link, and the address bar stops reading /#/evaluation.
 *
 * The server's fallback is what makes this safe: without it, reloading on
 * /evaluation would ask the server for a file that does not exist.
 */

/** Normalized to a leading slash with no trailing slash: "/", "/evaluation". */
function readPath(): string {
  const raw = window.location.pathname;

  if (!raw || raw === "/") {
    return "/";
  }

  return raw.length > 1 ? raw.replace(/\/+$/, "") : raw;
}

/**
 * Navigate from anywhere, including outside a component.
 *
 * pushState changes the URL and fires nothing, so the hook below would never
 * re-render. Dispatching popstate is what closes that gap -- the same event
 * the browser's own back button sends.
 */
export function navigateTo(next: string): void {
  const target = next.startsWith("/") ? next : `/${next}`;

  if (target !== window.location.pathname) {
    window.history.pushState(null, "", target);
  }

  window.dispatchEvent(new PopStateEvent("popstate"));
}

/**
 * Click handler for a real <a href>. Keeps the link a link -- right-click,
 * middle-click and "open in new tab" still work -- while a plain left-click
 * routes in place instead of reloading the whole bundle.
 */
export function linkTo(path: string) {
  return (event: React.MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    event.preventDefault();
    navigateTo(path);
  };
}

export function useHashRoute(): [string, (path: string) => void] {
  const [path, setPath] = useState(readPath);

  useEffect(() => {
    // Back and forward. pushState alone fires nothing, so navigate() sets
    // the state itself and this covers only the browser's own buttons.
    const onPop = () => setPath(readPath());

    window.addEventListener("popstate", onPop);

    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: string) => {
    const target = next.startsWith("/") ? next : `/${next}`;

    if (target !== window.location.pathname) {
      window.history.pushState(null, "", target);
    }

    setPath(target);
  }, []);

  return [path, navigate];
}
