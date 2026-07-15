"use client";

import { Badge } from "@/components/ui/Badge";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";

type RevenueTrendCardProps = {
  revenueThisMonth: number;
  revenueLastMonth: number;
  growthPercent: number | null;
  loading?: boolean;
};

function GrowthBadge({
  growthPercent,
  noPriorDataLabel,
}: {
  growthPercent: number | null;
  noPriorDataLabel: string;
}) {
  if (growthPercent === null) {
    return (
      <Badge className="bg-slate-100 text-slate-600 ring-slate-200/80">
        {noPriorDataLabel}
      </Badge>
    );
  }

  const isPositive = growthPercent >= 0;
  return (
    <Badge
      className={`gap-1 ${
        isPositive
          ? "bg-emerald-100 text-emerald-900 ring-emerald-200/80"
          : "bg-red-100 text-red-900 ring-red-200/80"
      }`}
    >
      {isPositive ? "▲" : "▼"} {Math.abs(growthPercent).toFixed(2)}%
    </Badge>
  );
}

export function RevenueTrendCard({
  revenueThisMonth,
  revenueLastMonth,
  growthPercent,
  loading = false,
}: RevenueTrendCardProps) {
  const { t } = useTranslation();
  const maxValue = Math.max(revenueThisMonth, revenueLastMonth, 1);
  const thisMonthWidth = Math.max(4, (revenueThisMonth / maxValue) * 100);
  const lastMonthWidth = Math.max(4, (revenueLastMonth / maxValue) * 100);

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("dashboard.revenueTrendTitle")}
        </h2>
        {loading ? (
          <div className="h-5 w-20 animate-pulse rounded-full bg-slate-200" />
        ) : (
          <GrowthBadge
            growthPercent={growthPercent}
            noPriorDataLabel={t("dashboard.revenueTrendNoPriorData")}
          />
        )}
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-slate-700">
              {t("dashboard.revenueTrendThisMonth")}
            </span>
            {loading ? (
              <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
            ) : (
              <span className="font-semibold text-slate-900">
                {formatMoney(revenueThisMonth)}
              </span>
            )}
          </div>
          <div className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-slate-900 transition-all"
              style={{ width: loading ? "0%" : `${thisMonthWidth}%` }}
            />
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-slate-500">
              {t("dashboard.revenueTrendLastMonth")}
            </span>
            {loading ? (
              <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
            ) : (
              <span className="font-medium text-slate-600">
                {formatMoney(revenueLastMonth)}
              </span>
            )}
          </div>
          <div className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-slate-300 transition-all"
              style={{ width: loading ? "0%" : `${lastMonthWidth}%` }}
            />
          </div>
        </div>
      </div>
    </article>
  );
}
