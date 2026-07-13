"use client";

import Link from "next/link";

import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type { QuotePipelineSummary } from "@/lib/types";

type QuotePipelineCardProps = {
  pipeline: QuotePipelineSummary | null;
  currency: string;
  loading?: boolean;
};

export function QuotePipelineCard({ pipeline, currency, loading = false }: QuotePipelineCardProps) {
  const { t } = useTranslation();

  const currencyRow = pipeline?.by_currency.find((row) => row.currency_code === currency) ?? null;
  const acceptanceRate =
    pipeline?.acceptance_rate_percent != null ? `${pipeline.acceptance_rate_percent.toFixed(0)}%` : "—";

  return (
    <section aria-label={t("dashboard.quotePipelineTitle")} className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{t("dashboard.quotePipelineTitle")}</h2>
        <Link href="/quotes" className="text-sm font-medium text-slate-700 hover:text-slate-900">
          {t("dashboard.viewAll")}
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <DashboardCard
          title={t("dashboard.quotePipelinePendingLabel")}
          value={currencyRow ? formatCurrency(currencyRow.revenue_in_quotes, currency) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("dashboard.quotePipelineAcceptanceRateLabel")}
          value={acceptanceRate}
          loading={loading}
        />
        <DashboardCard
          title={t("dashboard.quotePipelineConvertedLabel")}
          value={currencyRow ? String(currencyRow.converted_this_month) : "—"}
          loading={loading}
        />
      </div>
    </section>
  );
}
