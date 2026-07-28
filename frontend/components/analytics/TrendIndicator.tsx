"use client";

import { Badge } from "@/components/ui/Badge";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TrendDirection } from "@/lib/types";

const DIRECTION_BADGE_CLASS: Record<TrendDirection, string> = {
  up: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  down: "bg-red-100 text-red-900 ring-red-200/80",
  flat: "bg-slate-100 text-slate-700 ring-slate-200/80",
  unknown: "bg-slate-100 text-slate-600 ring-slate-200/80",
};

const DIRECTION_ARROW: Record<TrendDirection, string> = {
  up: "▲",
  down: "▼",
  flat: "–",
  unknown: "",
};

type TrendIndicatorProps = {
  direction: TrendDirection;
  /** The API's own percentage_difference string, e.g. "20.80" -- null
   * exactly when direction is "unknown" (no previous baseline). This
   * component never recomputes a percentage from current/previous, only
   * formats the one the trend engine already computed. */
  percentageDifference: string | null;
};

/** The one reusable UP/DOWN/FLAT/UNKNOWN badge every comparison card in
 * this app renders -- see app.analytics.trend_direction.TrendDirection.
 * Deliberately a single shared component so a future addition (a new
 * comparison metric, an insight card) gets identical visual treatment
 * for free rather than reimplementing the arrow-and-color mapping. */
export function TrendIndicator({ direction, percentageDifference }: TrendIndicatorProps) {
  const { t } = useTranslation();

  if (direction === "unknown" || percentageDifference === null) {
    return (
      <Badge className={DIRECTION_BADGE_CLASS.unknown}>{t("analytics.trend.noPriorData")}</Badge>
    );
  }

  const magnitude = Math.abs(Number.parseFloat(percentageDifference)).toFixed(1);
  return (
    <Badge className={`gap-1 ${DIRECTION_BADGE_CLASS[direction]}`}>
      {DIRECTION_ARROW[direction] ? `${DIRECTION_ARROW[direction]} ` : ""}
      {magnitude}%
    </Badge>
  );
}
