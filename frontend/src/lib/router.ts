import { useCallback, useEffect, useState } from "react";

/**
 * Hash routing, hand-rolled.
 *
 * The app has exactly two screens and is served as a static bundle, so a
 * router dependency would cost more than it returns. Hash fragments also
 * survive being opened straight off the filesystem or behind any path
 * prefix, which `history.pushState` routing would not.
 */

/** Normalized to a leading slash with no trailing slash: "/", "/evaluation". */
function readHash(): string {
  const raw = window.location.hash.replace(/^#/, "");

  if (!raw || raw === "/") {
    return "/";
  }

  const withSlash = raw.startsWith("/") ? raw : `/${raw}`;

  return withSlash.length > 1 ? withSlash.replace(/\/+$/, "") : withSlash;
}

export function useHashRoute(): [string, (path: string) => void] {
  const [path, setPath] = useState(readHash);

  useEffect(() => {
    const onChange = () => setPath(readHash());

    window.addEventListener("hashchange", onChange);

    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: string) => {
    const target = next.startsWith("/") ? next : `/${next}`;

    // Assigning an identical hash fires no `hashchange`, so the state is
    // synced here rather than relying solely on the event.
    window.location.hash = target;
    setPath(target);
  }, []);

  return [path, navigate];
}
