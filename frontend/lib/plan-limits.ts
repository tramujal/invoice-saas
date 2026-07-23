import type { TranslateFn } from "@/lib/i18n/useTranslation";

/** NULL = unlimited, 0 = unavailable, positive integer = a hard limit --
 * see app.models.Plan's own docstring. The one place every page that
 * renders a plan limit (platform admin plans list, organization detail,
 * the tenant-facing read-only Plan & Limits page) converts that
 * convention into display text, so "Unlimited" always renders
 * identically everywhere. */
export function formatPlanLimit(value: number | null, t: TranslateFn): string {
  if (value === null) return t("planLimits.unlimited");
  if (value === 0) return t("planLimits.unavailable");
  return value.toLocaleString();
}
