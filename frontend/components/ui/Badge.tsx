import type { ReactNode } from "react";

type BadgeProps = {
  children: ReactNode;
  /** Color classes only (background, text, ring) -- shape/spacing come
   * from this component, converging every status/role/type pill in the app
   * onto the one shape that already won out in practice (PaymentStatusBadge). */
  className?: string;
};

export function Badge({ children, className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${className}`}
    >
      {children}
    </span>
  );
}
