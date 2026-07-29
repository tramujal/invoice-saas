"use client";

import { ButtonLink } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { useTranslation } from "@/lib/i18n/useTranslation";

/** Where Stripe's own hosted checkout page redirects the browser back to
 * if the tenant abandons or cancels checkout (see PlanSelector's
 * cancel_url). Nothing about the organization's plan or subscription
 * changed -- no webhook event was ever sent for an abandoned session --
 * so this is purely informational. */
export default function CheckoutCancelPage() {
  const { t } = useTranslation();

  return (
    <div className="mx-auto max-w-lg space-y-6 text-center">
      <PageHeader title={t("checkoutCancel.title")} subtitle={t("checkoutCancel.subtitle")} />
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
        <p className="text-sm text-slate-600">{t("checkoutCancel.message")}</p>
      </div>
      <ButtonLink href="/settings/plan">{t("checkoutCancel.backToPlan")}</ButtonLink>
    </div>
  );
}
