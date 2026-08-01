/** Phase UX4 -- the one shared loading-skeleton primitive. Every loading
 * state in the app before this hand-rolled its own `animate-pulse`
 * div with a slightly different height/width/radius combination
 * (DashboardCard, the dashboard's recent-invoices rows, various admin
 * detail pages) -- functionally identical, visually inconsistent.
 * Converging on one component is the same "one primitive, many call
 * sites" pattern Button/Badge/Input already established. */

type SkeletonProps = {
  className?: string;
  /** "text" (default) rounds like a line of text; "circle" for
   * avatar/icon-shaped placeholders. */
  variant?: "text" | "circle";
};

export function Skeleton({ className = "", variant = "text" }: SkeletonProps) {
  return (
    <div
      aria-hidden
      className={`animate-pulse bg-slate-200 ${variant === "circle" ? "rounded-full" : "rounded-md"} ${className}`}
    />
  );
}

/** A row of skeleton lines, e.g. for a list/table placeholder while data
 * loads -- `lines` independent-width bars so the placeholder doesn't
 * read as one suspiciously uniform block. */
export function SkeletonLines({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={`h-3.5 ${i === lines - 1 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}
