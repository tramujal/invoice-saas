"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationPermissions } from "@/lib/auth-storage";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { hasPermission } from "@/lib/permissions";
import type { StartPortalSessionRequest, StartPortalSessionResponse } from "@/lib/types";

/** Phase 19 -- redirects to the provider's own hosted billing-management
 * page (Stripe's "Customer Portal" and its equivalents): update a
 * payment method, view invoices, cancel a plan, all on the provider's
 * own UI, never rendered by this app (see app.routers.billing's own
 * module docstring on why no payment UI exists here). Requires the
 * organization to already have a provider customer on file (created by
 * its first checkout) -- a 404 from the backend means "you haven't
 * subscribed via checkout yet," surfaced as a plain, translated message
 * rather than the backend's own detail text. */
export function ManageBillingButton() {
  const { t } = useTranslation();
  const toast = useToast();
  const [loading, setLoading] = useState(false);
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

  if (!canManageBilling) return null;

  async function handleClick() {
    setLoading(true);
    try {
      const body: StartPortalSessionRequest = {
        return_url: window.location.href,
      };
      const response = await apiFetch<StartPortalSessionResponse>(orgPath("billing/portal"), {
        method: "POST",
        body: JSON.stringify(body),
      });
      window.location.href = response.portal_url;
    } catch (err) {
      const isNotFound =
        typeof err === "object" &&
        err !== null &&
        "status" in err &&
        (err as { status?: number }).status === 404;
      toast.error(
        isNotFound
          ? t("manageBilling.noCustomerYet")
          : formatApiError(err, t("manageBilling.error"))
      );
      setLoading(false);
    }
  }

  return (
    <Button type="button" variant="secondary" size="sm" onClick={handleClick} disabled={loading}>
      {loading ? t("manageBilling.opening") : t("manageBilling.button")}
    </Button>
  );
}
