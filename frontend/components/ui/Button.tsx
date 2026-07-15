import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

/** The app's one shared button primitive. Converges the ~5-6 padding
 * combinations that had accumulated across hand-rolled buttons onto a
 * single size scale, and standardizes on focus-visible: (keyboard-only
 * focus ring) instead of the focus:/focus-visible: mix that existed
 * before. Colors/radii were already consistent app-wide (primary =
 * slate-900 fill, secondary = slate-200 outline) -- only padding and
 * focus-ring behavior actually needed converging. */

export type ButtonVariant = "primary" | "secondary" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    "bg-slate-900 text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70",
  secondary:
    "border border-slate-200 bg-white text-slate-800 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50",
  danger:
    "bg-red-600 text-white shadow-sm hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-70",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2.5 text-sm",
};

const BASE_CLASS =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold outline-none transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400";

function variantClasses(variant: ButtonVariant, size: ButtonSize, className?: string): string {
  return [BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className]
    .filter(Boolean)
    .join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button className={variantClasses(variant, size, className)} {...rest}>
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
