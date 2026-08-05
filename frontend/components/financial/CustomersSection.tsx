"use client";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { CustomersSectionResponse } from "@/lib/types";

type CustomersSectionProps = {
  data: CustomersSectionResponse | null;
  loading: boolean;
};

function MiniTable({
  title,
  rows,
}: {
  title: string;
  rows: { name: string; value: string }[];
}) {
  return (
    <div className={TABLE_WRAPPER_CLASS}>
      <div className="border-b border-slate-200 px-4 py-3 sm:px-6">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className={TABLE_CLASS}>
          <tbody className={TABLE_BODY_CLASS}>
            {rows.length === 0 ? (
              <tr>
                <td className={TABLE_CELL_CLASS}>—</td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr key={i} className={TABLE_ROW_CLASS}>
                  <td className={TABLE_CELL_CLASS}>{row.name}</td>
                  <td className={`${TABLE_CELL_CLASS} text-right font-medium`}>{row.value}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Section 4 -- top customers by revenue/outstanding/overdue, revenue
 * concentration, repeat-customer contribution, customer growth, and a
 * transparent at-risk list (each entry names exactly which deterministic
 * rule fired -- see AtRiskCustomer.rule -- never an opaque AI judgment). */
export function CustomersSection({ data, loading }: CustomersSectionProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <section aria-label={t("financial.customersHeading")} className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.customersHeading")}</h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </section>
    );
  }

  const hasData = data && (data.top_by_revenue.length > 0 || data.top_by_outstanding.length > 0);

  return (
    <section aria-label={t("financial.customersHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.customersHeading")}</h2>

      {!hasData ? (
        <EmptyState title={t("financial.customersEmptyTitle")} description={t("financial.customersEmptyDescription")} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("financial.customerGrowthLabel")}
              </dt>
              <dd className="mt-1 text-lg font-semibold text-slate-900">{data?.customer_growth_count ?? 0}</dd>
            </div>
            {(data?.concentration ?? []).map((c) => (
              <div key={c.currency_code} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {t("financial.concentrationLabel", { currency: c.currency_code })}
                </dt>
                <dd className="mt-1 text-lg font-semibold text-slate-900">
                  {c.top_customer_share_percent !== null ? `${Number(c.top_customer_share_percent).toFixed(1)}%` : "—"}
                </dd>
              </div>
            ))}
            {(data?.repeat_contribution ?? []).map((r) => (
              <div key={r.currency_code} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {t("financial.repeatCustomersLabel", { currency: r.currency_code })}
                </dt>
                <dd className="mt-1 text-lg font-semibold text-slate-900">
                  {r.repeat_customer_count} / {r.total_customer_count}
                </dd>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <MiniTable
              title={t("financial.topByRevenue")}
              rows={(data?.top_by_revenue ?? []).map((c) => ({
                name: c.customer_name,
                value: `${c.currency_code} ${formatMoney(Number(c.revenue))}`,
              }))}
            />
            <MiniTable
              title={t("financial.topByOutstanding")}
              rows={(data?.top_by_outstanding ?? []).map((c) => ({
                name: c.customer_name,
                value: `${c.currency_code} ${formatMoney(Number(c.outstanding_total))}`,
              }))}
            />
            <MiniTable
              title={t("financial.mostOverdue")}
              rows={(data?.most_overdue ?? []).map((c) => ({
                name: c.customer_name,
                value: `${c.currency_code} ${formatMoney(Number(c.overdue_total))}`,
              }))}
            />
          </div>

          {(data?.at_risk.length ?? 0) > 0 ? (
            <div className={TABLE_WRAPPER_CLASS}>
              <div className="border-b border-slate-200 px-4 py-3 sm:px-6">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {t("financial.atRiskHeading")}
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className={TABLE_CLASS}>
                  <thead className={TABLE_HEAD_CLASS}>
                    <tr>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colCustomer")}</th>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colEvidence")}</th>
                    </tr>
                  </thead>
                  <tbody className={TABLE_BODY_CLASS}>
                    {data!.at_risk.map((entry, i) => (
                      <tr key={i} className={TABLE_ROW_CLASS}>
                        <td className={TABLE_CELL_CLASS}>
                          <div className="flex items-center gap-2">
                            {entry.customer_name}
                            <Badge className="bg-amber-50 text-amber-700 ring-amber-200">
                              {t(`financial.atRiskRule.${entry.rule}`)}
                            </Badge>
                          </div>
                        </td>
                        <td className={TABLE_CELL_CLASS}>{entry.evidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
