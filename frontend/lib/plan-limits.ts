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

/** Phase 14B's used-against-limit sibling of formatPlanLimit above --
 * same NULL/0/positive convention on `limit`, but renders "{used} / {limit}"
 * when there is a real ceiling to compare against, since usage without its
 * limit ("18") is meaningless on its own. Never shows a percentage or a
 * warning color; this is a plain measurement, not an enforcement signal. */
export function formatUsage(used: number, limit: number | null, t: TranslateFn): string {
  if (limit === null) return t("planLimits.unlimited");
  if (limit === 0) return t("planLimits.unavailable");
  return `${used.toLocaleString()} / ${limit.toLocaleString()}`;
}

/** Phase 14C's purely-visual sibling of formatUsage above -- never blocks
 * anything from wherever it's rendered, it just flags a resource that's
 * at or close to its plan limit so the tenant/admin can see it coming.
 * Only meaningful against a real, positive limit: unlimited (null) and
 * unavailable (0) resources can never be "reached" or "near" in any
 * useful sense, so both return null for them. */
export function getLimitStatus(used: number, limit: number | null): "reached" | "near" | null {
  if (limit === null || limit <= 0) return null;
  if (used >= limit) return "reached";
  if (used / limit > 0.9) return "near";
  return null;
}
