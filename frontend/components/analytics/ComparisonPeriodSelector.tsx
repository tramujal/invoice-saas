"use client";

import { Select } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { COMPARISON_PERIOD_KINDS, type ComparisonPeriodKind } from "@/lib/types";

const COMPARISON_LABEL_KEY: Record<ComparisonPeriodKind, string> = {
  current_month: "analytics.comparison.currentMonth",
  current_quarter: "analytics.comparison.currentQuarter",
  current_year: "analytics.comparison.currentYear",
  last_7_days: "analytics.comparison.last7Days",
  last_30_days: "analytics.comparison.last30Days",
};

type ComparisonPeriodSelectorProps = {
  value: ComparisonPeriodKind;
  onChange: (next: ComparisonPeriodKind) => void;
};

/** Picks which of the 5 supported comparison kinds GET .../analytics/
 * trends is queried with -- same native-<select> reasoning as
 * TimeWindowSelector (a fixed, small option set at any viewport width). */
export function ComparisonPeriodSelector({ value, onChange }: ComparisonPeriodSelectorProps) {
  const { t } = useTranslation();

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only">{t("analytics.comparisonLabel")}</span>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value as ComparisonPeriodKind)}
        aria-label={t("analytics.comparisonLabel")}
        fullWidth={false}
        className="min-w-[10rem]"
      >
        {COMPARISON_PERIOD_KINDS.map((kind) => (
          <option key={kind} value={kind}>
            {t(COMPARISON_LABEL_KEY[kind])}
          </option>
        ))}
      </Select>
    </label>
  );
}
