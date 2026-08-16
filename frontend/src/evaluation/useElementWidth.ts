import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Measures an element's rendered width.
 *
 * The SVG charts draw at their true pixel size rather than scaling a fixed
 * viewBox, because scaling shrinks axis labels along with everything else —
 * a chart in a four-column panel would render its text at around 4px. Knowing
 * the real width lets the chart keep type at a fixed, legible size and give
 * the extra room to the plot instead.
 */
export function useElementWidth<T extends HTMLElement>(): [
  (node: T | null) => void,
  number,
] {
  const [width, setWidth] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);

  const ref = useCallback((node: T | null) => {
    observerRef.current?.disconnect();

    if (!node) {
      return;
    }

    setWidth(node.getBoundingClientRect().width);

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });

    observer.observe(node);
    observerRef.current = observer;
  }, []);

  useEffect(() => () => observerRef.current?.disconnect(), []);

  return [ref, width];
}
