"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { ApiError, apiFetch, publicGet } from "@/lib/api";
import {
  isAuthenticated,
  updateActiveOrganization,
} from "@/lib/auth-storage";
import { formatApiError, getApiErrorCode, isRateLimitedError } from "@/lib/format-api-error";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import { getMembershipRoleLabel } from "@/lib/membership-role";
import type { OrganizationProfile, PublicInvitation, PublicInvitationAcceptResponse } from "@/lib/types";

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
  | "error";

function AcceptInvitationContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t, language, setLanguage } = useMarketingTranslation();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<Status>(token ? "loading" : "missing-token");
  const [invitation, setInvitation] = useState<PublicInvitation | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
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
      if (code === "invitation_email_mismatch") {
        setStatus("email-mismatch");
      } else if (code === "invitation_expired") {
        setStatus("expired");
      } else if (code === "invitation_already_accepted") {
        setStatus("already-accepted");
      } else if (isRateLimitedError(err)) {
        setStatus("rate-limited");
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
            <Link
              href="/login"
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("invitation.goToLogin")}
            </Link>
          </>
        ) : null}

        {status === "expired" ? (
          <>
            <p className="mt-3 text-sm text-red-600" role="alert">
              {t("invitation.expiredMessage")}
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("invitation.goToLogin")}
            </Link>
          </>
        ) : null}

        {status === "already-accepted" ? (
          <>
            <p className="mt-3 text-sm text-amber-700" role="alert">
              {t("invitation.alreadyAcceptedMessage")}
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("invitation.goToLogin")}
            </Link>
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
              <button
                type="button"
                onClick={() => void handleAccept()}
                disabled={status === "accepting"}
                className="mt-6 w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {status === "accepting" ? t("invitation.accepting") : t("invitation.acceptButton")}
              </button>
            ) : (
              <div className="mt-6 flex flex-col gap-2">
                <Link
                  href={loginNext}
                  className="inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
                >
                  {t("invitation.signInToAccept")}
                </Link>
                <Link
                  href={registerNext}
                  className="inline-flex w-full items-center justify-center rounded-lg border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-800 transition hover:bg-slate-50"
                >
                  {t("invitation.registerToAccept")}
                </Link>
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
