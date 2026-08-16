import { useId } from "react";
import "./Logo.css";

/**
 * The Financial Intelligence brand mark.
 *
 * Geometry, not illustration: a stem and arm form an implied `F` that doubles
 * as a chart's y-axis, and two ascending bars to its right carry the growth
 * reading. Four solid shapes, no strokes and no internal detail, so the mark
 * survives down to 24px where a monogram or a node network would turn to mush.
 *
 * The tile carries the only gradient — blue into teal — which ties the mark to
 * the header band behind it. The bars stay solid white rather than taking the
 * emerald accent: at 24px, green on teal loses too much separation to read.
 *
 * Decorative by default, because the product name sits beside it in the
 * masthead. Pass a `title` where the mark stands alone.
 */
export function Logo({
  size = 36,
  title,
}: {
  size?: number;
  /** Supplying this exposes the mark to assistive tech as an image. */
  title?: string;
}) {
  // Two instances on one page would otherwise share a gradient id.
  const gradientId = useId();

  return (
    <svg
      className="logo"
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : "true"}
      aria-label={title}
    >
      {title && <title>{title}</title>}

      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--brand-blue)" />
          <stop offset="0.55" stopColor="var(--brand-blue-deep)" />
          <stop offset="1" stopColor="var(--brand-teal)" />
        </linearGradient>
      </defs>

      <rect width="40" height="40" rx="11" fill={`url(#${gradientId})`} />

      {/* Implied F: stem doubling as the chart axis, plus its top arm. */}
      <rect x="9" y="9" width="5" height="22" rx="1.6" fill="#fff" />
      <rect x="9" y="9" width="9.5" height="5" rx="1.6" fill="#fff" />

      {/* Ascending bars — data into growth. */}
      <rect x="19.5" y="22" width="5" height="9" rx="1.6" fill="#fff" fillOpacity="0.78" />
      <rect x="27" y="16.5" width="5" height="14.5" rx="1.6" fill="#fff" />
    </svg>
  );
}
