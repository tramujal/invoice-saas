"use client";

import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { QuotesSectionResponse } from "@/lib/types";

type QuotesFunnelSectionProps = {
  data: QuotesSectionResponse | null;
  loading: boolean;
};

const FUNNEL_STAGES: Array<{ key: keyof QuotesSectionResponse["counts"]; labelKey: string }> = [
  { key: "created", labelKey: "financial.funnel.created" },
  { key: "sent", labelKey: "financial.funnel.sent" },
  { key: "accepted", labelKey: "financial.funnel.accepted" },
  { key: "rejected", labelKey: "financial.funnel.rejected" },
  { key: "expired", labelKey: "financial.funnel.expired" },
  { key: "converted", labelKey: "financial.funnel.converted" },
];

/** Section 6 -- the quote funnel: counts at each stage, conversion %, and
 * average time-to-acceptance (an approximation -- Quote has no dedicated
 * acceptance timestamp, see average_time_to_acceptance_days's own note,
 * shown verbatim below the number). */
export function QuotesFunnelSection({ data, loading }: QuotesFunnelSectionProps) {
  const { t } = useTranslation();
  const maxCount = data ? Math.max(1, ...FUNNEL_STAGES.map((s) => data.counts[s.key])) : 1;

  return (
    <section aria-label={t("financial.quotesHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.quotesHeading")}</h2>

      {loading ? (
        <Skeleton className="h-56 w-full" />
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="space-y-2.5">
            {FUNNEL_STAGES.map((stage) => {
              const count = data?.counts[stage.key] ?? 0;
              const width = data ? Math.max(4, (count / maxCount) * 100) : 4;
              return (
                <div key={stage.key} className="flex items-center gap-3">
                  <span className="w-24 shrink-0 text-xs font-medium text-slate-600">{t(stage.labelKey)}</span>
                  <div className="h-6 flex-1 overflow-hidden rounded-md bg-slate-100">
                    <div
                      className="h-full rounded-md bg-slate-900 transition-all duration-500"
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-sm font-semibold text-slate-900">{count}</span>
                </div>
              );
            })}
          </div>

          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-slate-200 px-4 py-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("financial.conversionRateLabel")}
              </dt>
              <dd className="mt-1 text-lg font-semibold text-slate-900">
                {data?.conversion_rate_percent !== null && data?.conversion_rate_percent !== undefined
                  ? `${Number(data.conversion_rate_percent).toFixed(2)}%`
                  : t("financial.noPriorData")}
              </dd>
            </div>
            <div className="rounded-xl border border-slate-200 px-4 py-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("financial.avgAcceptanceTimeLabel")}
              </dt>
              <dd className="mt-1 text-lg font-semibold text-slate-900">
                {data?.average_time_to_acceptance_days.value !== null &&
                data?.average_time_to_acceptance_days.value !== undefined
                  ? t("financial.daysCount", { count: data.average_time_to_acceptance_days.value })
                  : t("financial.noPriorData")}
              </dd>
              {data?.average_time_to_acceptance_days.value !== null &&
              data?.average_time_to_acceptance_days.value !== undefined ? (
                <dd className="mt-1 text-xs text-slate-400">{t("financial.avgAcceptanceTimeApproximate")}</dd>
              ) : null}
            </div>
          </div>

          {(data?.by_currency.length ?? 0) > 0 ? (
            <div className="mt-4 flex flex-wrap gap-3 border-t border-slate-100 pt-4 text-xs text-slate-600">
              {data!.by_currency.map((c) => (
                <span key={c.currency_code}>
                  {c.currency_code}: {t("financial.quotedVsConverted", {
                    quoted: formatMoney(Number(c.quoted_value)),
                    converted: formatMoney(Number(c.converted_value)),
                  })}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
