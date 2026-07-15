"use client";

import { Badge } from "@/components/ui/Badge";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  PAYMENT_STATUSES,
  PAYMENT_STATUS_BADGE_CLASS,
  getPaymentStatusLabel,
} from "@/lib/payment-status";

const BAR_COLOR_CLASS: Record<(typeof PAYMENT_STATUSES)[number], string> = {
  pending: "bg-amber-400",
  paid: "bg-emerald-500",
  overdue: "bg-red-400",
};

type PaymentStatusBreakdownProps = {
  pending: number;
  paid: number;
  overdue: number;
  loading?: boolean;
};

export function PaymentStatusBreakdown({
  pending,
  paid,
  overdue,
  loading = false,
}: PaymentStatusBreakdownProps) {
  const { t } = useTranslation();
  const counts = { pending, paid, overdue };
  const total = pending + paid + overdue;

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("dashboard.paymentStatusBreakdownTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 space-y-3" aria-hidden>
          <div className="h-2.5 w-full animate-pulse rounded-full bg-slate-200" />
          {PAYMENT_STATUSES.map((status) => (
            <div key={status} className="flex items-center justify-between">
              <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
              <div className="h-4 w-8 animate-pulse rounded bg-slate-200" />
            </div>
          ))}
        </div>
      ) : total === 0 ? (
        <p className="mt-5 text-sm text-slate-500">
          {t("dashboard.paymentStatusBreakdownEmpty")}
        </p>
      ) : (
        <>
          <div className="mt-5 flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            {PAYMENT_STATUSES.map((status) => {
              const share = (counts[status] / total) * 100;
              if (share === 0) return null;
              return (
                <div
                  key={status}
                  className={BAR_COLOR_CLASS[status]}
                  style={{ width: `${share}%` }}
                  title={`${getPaymentStatusLabel(t, status)}: ${counts[status]}`}
                />
              );
            })}
          </div>

          <ul className="mt-4 space-y-2.5">
            {PAYMENT_STATUSES.map((status) => (
              <li
                key={status}
                className="flex items-center justify-between text-sm"
              >
                <Badge className={PAYMENT_STATUS_BADGE_CLASS[status]}>
                  {getPaymentStatusLabel(t, status)}
                </Badge>
                <span className="font-medium text-slate-700">
                  {counts[status]}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
