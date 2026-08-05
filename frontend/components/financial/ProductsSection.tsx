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
import type { FinancialProductTrend, ProductsSectionResponse } from "@/lib/types";

const TREND_BADGE_CLASS: Record<FinancialProductTrend["direction"], string> = {
  increasing: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  decreasing: "bg-red-50 text-red-700 ring-red-200",
  flat: "bg-slate-100 text-slate-600 ring-slate-200",
  insufficient_data: "bg-slate-100 text-slate-500 ring-slate-200",
};

type ProductsSectionProps = {
  data: ProductsSectionResponse | null;
  loading: boolean;
};

/** Section 5 -- top products/services by revenue, with quantity sold,
 * average sale value, contribution % of that currency's total, and a
 * transparent (never AI-guessed) increasing/decreasing/flat trend badge
 * derived from 6 months of history (see build_products_section). */
export function ProductsSection({ data, loading }: ProductsSectionProps) {
  const { t } = useTranslation();
  const trendByProduct = new Map((data?.trends ?? []).map((tr) => [`${tr.product_id}:${tr.currency_code}`, tr]));
  const concentrationByCurrency = new Map((data?.concentration ?? []).map((c) => [c.currency_code, c]));

  return (
    <section aria-label={t("financial.productsHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.productsHeading")}</h2>

      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : !data || data.by_revenue.length === 0 ? (
        <EmptyState title={t("financial.productsEmptyTitle")} description={t("financial.productsEmptyDescription")} />
      ) : (
        <div className={TABLE_WRAPPER_CLASS}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colProduct")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colRevenue")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colQuantity")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colAverageSale")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colContribution")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colTrend")}</th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {data.by_revenue.map((p) => {
                  const trend = trendByProduct.get(`${p.product_id}:${p.currency_code}`);
                  const concentration = concentrationByCurrency.get(p.currency_code);
                  const share =
                    concentration?.top_product_share_percent !== null &&
                    concentration?.top_product_share_percent !== undefined
                      ? `${Number(concentration.top_product_share_percent).toFixed(1)}%`
                      : "—";
                  return (
                    <tr key={`${p.product_id}:${p.currency_code}`} className={TABLE_ROW_CLASS}>
                      <td className={TABLE_CELL_CLASS}>{p.product_name}</td>
                      <td className={TABLE_CELL_CLASS}>
                        {p.currency_code} {formatMoney(Number(p.revenue))}
                      </td>
                      <td className={TABLE_CELL_CLASS}>{p.quantity}</td>
                      <td className={TABLE_CELL_CLASS}>
                        {p.currency_code} {formatMoney(Number(p.average_sale_value))}
                      </td>
                      <td className={TABLE_CELL_CLASS}>{share}</td>
                      <td className={TABLE_CELL_CLASS}>
                        {trend ? (
                          <Badge className={TREND_BADGE_CLASS[trend.direction]}>
                            {t(`financial.productTrend.${trend.direction}`)}
                          </Badge>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
