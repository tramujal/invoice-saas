import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

/** The app's one shared button primitive. Converges the ~5-6 padding
 * combinations that had accumulated across hand-rolled buttons onto a
 * single size scale, and standardizes on focus-visible: (keyboard-only
 * focus ring) instead of the focus:/focus-visible: mix that existed
 * before. Colors/radii were already consistent app-wide (primary =
 * slate-900 fill, secondary = slate-200 outline) -- only padding and
 * focus-ring behavior actually needed converging.
 *
 * Phase UX4 adds `loading` -- a spinner + forced-disabled state, so the
 * ~15 call sites that were hand-rolling their own
 * `{submitting ? "Saving…" : "Save"}` text swap (with no visual spinner)
 * can opt into one consistent treatment instead of each inventing its
 * own. Purely additive: omitting `loading` behaves exactly as before. */

export type ButtonVariant = "primary" | "secondary" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    "bg-slate-900 text-white shadow-sm hover:bg-slate-800 hover:shadow active:bg-slate-950 disabled:cursor-not-allowed disabled:opacity-70",
  secondary:
    "border border-slate-200 bg-white text-slate-800 shadow-sm hover:bg-slate-50 hover:border-slate-300 active:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50",
  danger:
    "bg-red-600 text-white shadow-sm hover:bg-red-700 hover:shadow active:bg-red-800 disabled:cursor-not-allowed disabled:opacity-70",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2.5 text-sm",
};

const BASE_CLASS =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold outline-none transition duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400";

function variantClasses(variant: ButtonVariant, size: ButtonSize, className?: string): string {
  return [BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className]
    .filter(Boolean)
    .join(" ");
}

function ButtonSpinner() {
  return (
    <svg className="h-4 w-4 shrink-0 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
  /** Shows a spinner in place of the button's own icon slot and forces
   * `disabled` -- callers still pass their own loading-aware label text
   * (e.g. "Saving…") as `children`; this only adds the visual spinner
   * and the disabled guard against a double-submit. */
  loading?: boolean;
};

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  loading = false,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={variantClasses(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <ButtonSpinner /> : null}
      {children}
    </button>
  );
}

type ButtonLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
};

/** Same visual treatment as Button, for navigational actions (e.g. "New
 * Invoice") that should be a real link, not a button with a router push. */
export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link href={href} className={variantClasses(variant, size, className)} {...rest}>
      {children}
    </Link>
  );
}
