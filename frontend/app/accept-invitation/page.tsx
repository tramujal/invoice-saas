"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { Button, ButtonLink } from "@/components/ui/Button";
import { ApiError, apiFetch, publicGet } from "@/lib/api";
import {
  isAuthenticated,
  updateActiveOrganization,
} from "@/lib/auth-storage";
import {
  formatApiError,
  getApiErrorCode,
  getPlanLimitReachedDetail,
  isRateLimitedError,
} from "@/lib/format-api-error";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import { getMembershipRoleLabel } from "@/lib/membership-role";
import type {
  OrganizationProfile,
  PlanLimitReachedDetail,
  PublicInvitation,
  PublicInvitationAcceptResponse,
} from "@/lib/types";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

type Status =
  | "loading"
  | "missing-token"
  | "not-found"
  | "expired"
  | "already-accepted"
  | "ready"
  | "accepting"
  | "accepted"
  | "email-mismatch"
  | "rate-limited"
  | "plan-limit-reached"
  | "error";

function AcceptInvitationContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t, language, setLanguage } = useMarketingTranslation();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<Status>(token ? "loading" : "missing-token");
  const [invitation, setInvitation] = useState<PublicInvitation | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [planLimitDetail, setPlanLimitDetail] = useState<PlanLimitReachedDetail | null>(null);
  const hasLoaded = useRef(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const res = await publicGet<PublicInvitation>(defaultApi, `/invitations/public/${token}`);
      setInvitation(res);
      if (res.already_accepted) setStatus("already-accepted");
      else if (res.expired) setStatus("expired");
      else setStatus("ready");
    } catch (err) {
      setStatus(err instanceof ApiError && err.status === 404 ? "not-found" : "error");
    }
  }, [token]);

  useEffect(() => {
    if (!token || hasLoaded.current) return;
    hasLoaded.current = true;
    void load();
  }, [token, load]);

  async function handleAccept() {
    if (!token) return;
    setStatus("accepting");
    try {
      const res = await apiFetch<PublicInvitationAcceptResponse>(`/invitations/public/${token}/accept`, {
        method: "POST",
      });

      updateActiveOrganization({
        organizationId: res.organization_id,
        organizationName: res.organization_name,
      });
      // Best-effort: fetch the joined org's currency/language too, so the
      // dashboard the user lands on next isn't briefly showing stale
      // values carried over from whichever org was previously active.
      try {
        const profile = await apiFetch<OrganizationProfile>(`/organizations/${res.organization_id}`);
        updateActiveOrganization({
          organizationId: res.organization_id,
          organizationCurrency: profile.currency_code,
          organizationLanguage: profile.language,
        });
      } catch {
        // Non-fatal -- the org switch itself already succeeded above.
      }

      setStatus("accepted");
      router.replace("/dashboard");
    } catch (err) {
      const code = getApiErrorCode(err);
      const planLimit = getPlanLimitReachedDetail(err);
      if (code === "invitation_email_mismatch") {
        setStatus("email-mismatch");
      } else if (code === "invitation_expired") {
        setStatus("expired");
      } else if (code === "invitation_already_accepted") {
        setStatus("already-accepted");
      } else if (isRateLimitedError(err)) {
        setStatus("rate-limited");
      } else if (planLimit) {
        setPlanLimitDetail(planLimit);
        setStatus("plan-limit-reached");
      } else {
        setErrorMessage(formatApiError(err, t("invitation.errorGeneric")));
        setStatus("error");
      }
    }
  }

  const loginNext = token
    ? `/login?next=${encodeURIComponent(`/accept-invitation?token=${token}`)}`
    : "/login";
  const registerNext = token
    ? `/login?mode=register&next=${encodeURIComponent(`/accept-invitation?token=${token}`)}`
    : "/login?mode=register";

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex justify-end">
          <LanguageSwitcher language={language} setLanguage={setLanguage} t={t} />
        </div>

        <h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-900">
          {t("invitation.heading")}
        </h1>

        {status === "loading" ? (
          <p className="mt-3 text-sm text-slate-600" role="status">
            {t("invitation.loading")}
          </p>
        ) : null}

        {status === "missing-token" || status === "not-found" ? (
          <>
            <p className="mt-3 text-sm text-red-600" role="alert">
              {t("invitation.notFound")}
            </p>
            <ButtonLink href="/login" className="mt-6 w-full">
              {t("invitation.goToLogin")}
            </ButtonLink>
          </>
        ) : null}

        {status === "expired" ? (
          <>
            <p className="mt-3 text-sm text-red-600" role="alert">
              {t("invitation.expiredMessage")}
            </p>
            <ButtonLink href="/login" className="mt-6 w-full">
              {t("invitation.goToLogin")}
            </ButtonLink>
          </>
        ) : null}

        {status === "already-accepted" ? (
          <>
            <p className="mt-3 text-sm text-amber-700" role="alert">
              {t("invitation.alreadyAcceptedMessage")}
            </p>
            <ButtonLink href="/login" className="mt-6 w-full">
              {t("invitation.goToLogin")}
            </ButtonLink>
          </>
        ) : null}

        {status === "email-mismatch" ? (
          <>
            <p className="mt-3 text-sm text-red-600" role="alert">
              {t("invitation.emailMismatchMessage")}
            </p>
          </>
        ) : null}

        {status === "rate-limited" ? (
          <p className="mt-3 text-sm text-red-600" role="alert">
            {t("invitation.rateLimitedMessage")}
          </p>
        ) : null}

        {status === "error" ? (
          <p className="mt-3 text-sm text-red-600" role="alert">
            {errorMessage ?? t("invitation.errorGeneric")}
          </p>
        ) : null}

        {status === "plan-limit-reached" && planLimitDetail ? (
          <>
            <p className="mt-3 text-sm text-red-600" role="alert">
              {t("invitation.planLimitReachedMessage", { organization: invitation?.organization_name ?? "" })}
            </p>
            <dl className="mt-3 space-y-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-slate-500">{t("planAndLimits.rowUsers")}</dt>
                <dd className="font-medium text-slate-900">
                  {planLimitDetail.used.toLocaleString()} / {planLimitDetail.limit.toLocaleString()}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-500">{t("planAndLimits.currentPlanLabel")}</dt>
                <dd className="font-medium text-slate-900">{planLimitDetail.plan.name}</dd>
              </div>
            </dl>
          </>
        ) : null}

        {status === "accepted" ? (
          <p className="mt-3 text-sm text-emerald-700" role="status">
            {t("invitation.acceptedMessage")}
          </p>
        ) : null}

        {(status === "ready" || status === "accepting") && invitation ? (
          <>
            <p className="mt-3 text-sm text-slate-600">
              {t("invitation.inviteMessage", {
                organization: invitation.organization_name,
                role: getMembershipRoleLabel(t, invitation.role),
              })}
            </p>
            {invitation.inviter_email ? (
              <p className="mt-1 text-xs text-slate-400">
                {t("invitation.invitedByLabel", { email: invitation.inviter_email })}
              </p>
            ) : null}

            {isAuthenticated() ? (
              <Button
                type="button"
                onClick={() => void handleAccept()}
                disabled={status === "accepting"}
                className="mt-6 w-full"
              >
                {status === "accepting" ? t("invitation.accepting") : t("invitation.acceptButton")}
              </Button>
            ) : (
              <div className="mt-6 flex flex-col gap-2">
                <ButtonLink href={loginNext} className="w-full">
                  {t("invitation.signInToAccept")}
                </ButtonLink>
                <ButtonLink href={registerNext} variant="secondary" className="w-full">
                  {t("invitation.registerToAccept")}
                </ButtonLink>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={null}>
      <AcceptInvitationContent />
    </Suspense>
  );
}
