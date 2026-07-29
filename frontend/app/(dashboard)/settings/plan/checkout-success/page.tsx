"use client";

import { ButtonLink } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { useTranslation } from "@/lib/i18n/useTranslation";

/** Where Stripe's own hosted checkout page redirects the browser back to
 * after a successful payment (see PlanSelector's success_url). Never
 * fetches or displays anything provider-specific -- the organization's
 * plan hasn't necessarily changed the instant this page loads, since
 * that only happens once the checkout_completed webhook event actually
 * arrives (see app.billing.service.BillingService.sync_from_webhook_event),
 * which can take a few seconds. This page is deliberately just a
 * friendly acknowledgment, not a live status check. */
export default function CheckoutSuccessPage() {
  const { t } = useTranslation();

  return (
    <div className="mx-auto max-w-lg space-y-6 text-center">
      <PageHeader title={t("checkoutSuccess.title")} subtitle={t("checkoutSuccess.subtitle")} />
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6">
        <p className="text-sm text-emerald-800">{t("checkoutSuccess.message")}</p>
      </div>
      <ButtonLink href="/settings/plan">{t("checkoutSuccess.backToPlan")}</ButtonLink>
    </div>
  );
}
