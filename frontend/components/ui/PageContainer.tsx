import type { ReactNode } from "react";

/** How wide this page's CONTENT is allowed to get.
 *
 * The distinction that matters here is PAGE WIDTH vs READING WIDTH: the
 * page container should use the screen the user actually has, but a
 * settings form does not become more usable with 1600px-wide inputs, and
 * a paragraph of prose does not become more readable. So this is a small
 * closed set of intentions, not a free-form max-width prop -- a page
 * declares what KIND of content it holds and the layout system decides
 * the number.
 *
 * - "wide"   (default) Tables, dashboards, KPI grids, charts, list pages.
 *            Uses the full width `<main>` gives it. This is what most
 *            pages want and what makes the app feel like a desktop tool.
 * - "form"   Long vertical forms and settings panels. Wide enough to
 *            hold two columns comfortably, narrow enough that a text
 *            input doesn't stretch across a 27" monitor.
 * - "narrow" Prose/confirmation pages (checkout result, short notices)
 *            where line length is the constraint that matters.
 */
export type PageWidth = "wide" | "form" | "narrow";

/** `wide` deliberately has NO max-width below 2xl.
 *
 * `<main>` in AppShell/PlatformAdminShell is already `min-w-0 flex-1`
 * with `p-4 sm:p-6 md:p-8`, so the sidebar plus that 32px gutter is the
 * only fixed horizontal space at desktop -- exactly the intended
 * "sidebar | gutter | content | gutter" shape. Adding a max-width here
 * would re-introduce the centered-island problem this abstraction
 * exists to remove.
 *
 * The one ceiling, `2xl:max-w-[1800px]`, applies only above 1536px. It
 * exists because beyond roughly that width a data table stops being
 * easier to read and starts forcing genuine head-turning between the
 * first and last column on a 34" ultrawide. 1800px is far wider than the
 * 1152px (`max-w-6xl`) that pages used before, so a 1920px monitor still
 * gains ~650px of usable content width rather than losing any.
 */
const WIDTH_CLASS: Record<PageWidth, string> = {
  wide: "w-full 2xl:max-w-[1800px]",
  form: "w-full max-w-4xl",
  narrow: "w-full max-w-lg",
};

type PageContainerProps = {
  children: ReactNode;
  width?: PageWidth;
  /** Vertical rhythm between the page's own top-level sections. Pages
   * previously wrote `space-y-6` or `space-y-8` inline; both are kept as
   * options so this migration changes horizontal layout only. */
  spacing?: "6" | "8";
  /** Escape hatch for genuinely page-specific needs (extra bottom
   * padding under a sticky footer, a flex column for a full-height chat
   * view). Appended last so it can override. */
  className?: string;
};

/** The single wrapper every authenticated page renders inside.
 *
 * Before this existed, all 34 authenticated pages declared their own
 * `mx-auto max-w-*`, ranging from max-w-lg to max-w-6xl -- which is both
 * why large monitors showed a narrow centered island and why Invoices,
 * Customers, Analytics and Platform Admin each looked like a different
 * product. Centralizing it means a future change to how this app uses
 * horizontal space is one edit, not thirty-four.
 *
 * `mx-auto` is kept so that a non-"wide" page (or "wide" on an ultrawide
 * monitor, past the 2xl ceiling) stays centered in the available space
 * rather than hugging the sidebar.
 */
export function PageContainer({
  children,
  width = "wide",
  spacing = "6",
  className,
}: PageContainerProps) {
  const spacingClass = spacing === "8" ? "space-y-8" : "space-y-6";
  return (
    <div className={`mx-auto ${WIDTH_CLASS[width]} ${spacingClass}${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}
