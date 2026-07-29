"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Input";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationPermissions } from "@/lib/auth-storage";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import { hasPermission } from "@/lib/permissions";
import type {
  BillingPeriod,
  Plan,
  StartCheckoutRequest,
  StartCheckoutResponse,
  Subscription,
} from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

type PlanSelectorProps = {
  subscription: Subscription | null;
};

/** Phase 19 self-service checkout -- lets a tenant with Permission
 * .billing_manage (owner-only) move onto a different plan/billing period
 * without a platform admin's involvement. Never talks to Stripe (or any
 * provider) directly: it only calls this app's own
 * POST .../billing/checkout, which returns a `checkout_url` to redirect
 * to -- see app.billing.service.BillingService.start_checkout's own
 * docstring on why nothing about the organization's plan changes until
 * the provider's own checkout_completed webhook event arrives. */
export function PlanSelector({ subscription }: PlanSelectorProps) {
  const { t } = useTranslation();
  const toast = useToast();
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [billingPeriod, setBillingPeriod] = useState<BillingPeriod>("monthly");
  const [checkoutPlanId, setCheckoutPlanId] = useState<string | null>(null);

  // localStorage is unavailable during SSR, so reading permissions directly
  // in the render body would return a different result server- vs
  // client-side and trigger a hydration mismatch (see AppShell's identical
  // pattern) -- start from an empty array (matching SSR) and pick up the
  // real value only after mount.
  const [orgPermissions, setOrgPermissions] = useState<string[]>([]);

  useEffect(() => {
    setOrgPermissions(getOrganizationPermissions());
  }, []);

  const canManageBilling = hasPermission({ permissions: orgPermissions }, "billing.manage");

  useEffect(() => {
    // A member without billing.manage never sees this section at all
    // (see the early return below) -- skip the fetch entirely for them
    // rather than paying for a network call whose result renders
    // nothing. Hooks can't be called conditionally, so this check lives
    // inside the effect body instead of guarding the effect itself.
    if (!canManageBilling) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiFetch<Plan[]>(orgPath("billing/plans"))
      .then((rows) => {
        if (!cancelled) setPlans(rows);
      })
      .catch(() => {
        if (!cancelled) setError(GENERIC_LOAD_ERROR);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [canManageBilling]);

  async function handleChoosePlan(plan: Plan) {
    setCheckoutPlanId(plan.id);
    try {
      const origin = window.location.origin;
      const body: StartCheckoutRequest = {
        plan_id: plan.id,
        billing_period: billingPeriod,
        success_url: `${origin}/settings/plan/checkout-success`,
        cancel_url: `${origin}/settings/plan/checkout-cancel`,
      };
      const response = await apiFetch<StartCheckoutResponse>(orgPath("billing/checkout"), {
        method: "POST",
        body: JSON.stringify(body),
      });
      window.location.href = response.checkout_url;
    } catch (err) {
      toast.error(formatApiError(err, t("planSelector.checkoutError")));
      setCheckoutPlanId(null);
    }
  }

  if (!canManageBilling) {
    // Hidden, not disabled -- matches this app's existing convention
    // (see the team page's own "hide/restrict actions actor can't
    // perform" precedent) of never showing a control a member has no
    // path to actually use.
    return null;
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <h2 className="text-sm font-semibold text-slate-900">{t("planSelector.title")}</h2>
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">{t("planSelector.billingPeriodLabel")}</span>
          <Select
            value={billingPeriod}
            onChange={(e) => setBillingPeriod(e.target.value as BillingPeriod)}
            aria-label={t("planSelector.billingPeriodLabel")}
            fullWidth={false}
            className="min-w-[9rem]"
          >
            <option value="monthly">{t("planAndLimits.billingPeriodMonthly")}</option>
            <option value="yearly">{t("planAndLimits.billingPeriodYearly")}</option>
          </Select>
        </label>
      </div>

      {error ? (
        <div className="px-5 py-4 text-sm text-red-800" role="alert">
          {t("planSelector.loadError")}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        {loading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-48 animate-pulse rounded-xl border border-slate-100 bg-slate-50"
                aria-hidden
              />
            ))
          : (plans ?? []).map((plan) => {
              const isCurrentPlan = plan.id === subscription?.plan.id;
              const price = billingPeriod === "yearly" ? plan.yearly_price : plan.monthly_price;
              const isCheckingOut = checkoutPlanId === plan.id;

              return (
                <div
                  key={plan.id}
                  className={`flex flex-col justify-between rounded-xl border p-4 ${
                    isCurrentPlan ? "border-slate-900 ring-1 ring-slate-900" : "border-slate-200"
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-slate-900">{plan.name}</h3>
                      {isCurrentPlan ? (
                        <Badge className="bg-slate-900 text-white ring-slate-900">
                          {t("planSelector.currentPlanBadge")}
                        </Badge>
                      ) : null}
                    </div>
                    <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
                      {price === null
                        ? t("planSelector.customPricing")
                        : formatCurrency(price, plan.currency)}
                      {price !== null ? (
                        <span className="text-sm font-normal text-slate-500">
                          {billingPeriod === "yearly"
                            ? t("planSelector.perYear")
                            : t("planSelector.perMonth")}
                        </span>
                      ) : null}
                    </p>
                    {plan.description ? (
                      <p className="mt-2 text-sm text-slate-600">{plan.description}</p>
                    ) : null}
                  </div>
                  <Button
                    type="button"
                    variant={isCurrentPlan ? "secondary" : "primary"}
                    className="mt-4 w-full"
                    disabled={isCurrentPlan || isCheckingOut}
                    onClick={() => handleChoosePlan(plan)}
                  >
                    {isCurrentPlan
                      ? t("planSelector.currentPlanBadge")
                      : isCheckingOut
                        ? t("planSelector.startingCheckout")
                        : t("planSelector.choosePlan")}
                  </Button>
                </div>
              );
            })}
      </div>
    </section>
  );
}
