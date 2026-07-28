"use client";

import { Select } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { ANALYTICS_TIME_WINDOWS, type AnalyticsTimeWindowKind } from "@/lib/types";

const WINDOW_LABEL_KEY: Record<AnalyticsTimeWindowKind, string> = {
  today: "analytics.window.today",
  yesterday: "analytics.window.yesterday",
  last_7_days: "analytics.window.last7Days",
  last_30_days: "analytics.window.last30Days",
  current_month: "analytics.window.currentMonth",
  previous_month: "analytics.window.previousMonth",
  current_quarter: "analytics.window.currentQuarter",
  current_year: "analytics.window.currentYear",
};

type TimeWindowSelectorProps = {
  value: AnalyticsTimeWindowKind;
  onChange: (next: AnalyticsTimeWindowKind) => void;
};

/** The one control that picks which of the 8 non-custom TimeWindowKind
 * values GET /analytics/kpis is queried with. A native <select> rather
 * than a pill group (see CurrencySelector) -- 8 options would either wrap
 * awkwardly as pills or force a second row on mobile, while a select stays
 * a single, keyboard-and-touch-friendly control at any width. */
export function TimeWindowSelector({ value, onChange }: TimeWindowSelectorProps) {
  const { t } = useTranslation();

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only">{t("analytics.windowLabel")}</span>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value as AnalyticsTimeWindowKind)}
        aria-label={t("analytics.windowLabel")}
        fullWidth={false}
        className="min-w-[10rem]"
      >
        {ANALYTICS_TIME_WINDOWS.map((kind) => (
          <option key={kind} value={kind}>
            {t(WINDOW_LABEL_KEY[kind])}
          </option>
        ))}
      </Select>
    </label>
  );
}
