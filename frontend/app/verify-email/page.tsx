"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { apiFetch, authRequest } from "@/lib/api";
import {
  isAuthenticated,
  setEmailVerified as cacheEmailVerified,
} from "@/lib/auth-storage";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import type { MeResponse, MessageResponse } from "@/lib/types";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

type Status = "verifying" | "success" | "error" | "missing-token";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const { t, language, setLanguage } = useMarketingTranslation();
  const token = searchParams.get("token");
  const [status, setStatus] = useState<Status>(token ? "verifying" : "missing-token");
  // Guards against React 18 Strict Mode's dev-only double-invoke of
  // effects, which would otherwise consume this single-use token twice —
  // once succeeding, once failing — and could flash the error state.
  const hasRun = useRef(false);

  useEffect(() => {
    if (!token || hasRun.current) return;
    hasRun.current = true;

    async function run() {
      try {
        await authRequest<MessageResponse>(defaultApi, "/auth/verify-email", { token });
        setStatus("success");

        // Requirement: reflect the new verified state immediately, with no
        // navigation or page refresh needed. If this browser also holds a
        // valid session (e.g. verifying in a second tab of the same
        // browser used to register), re-fetch /auth/me right now and cache
        // the result — writing to localStorage fires a `storage` event in
        // every *other* open tab, which AppShell listens for, so an
        // already-open dashboard tab's banner disappears on its own.
        if (isAuthenticated()) {
          try {
            const me = await apiFetch<MeResponse>("/auth/me");
            cacheEmailVerified(me.user.email_verified);
          } catch {
            // Non-fatal: verification itself already succeeded above: the
            // banner will simply catch up next time /auth/me is reachable.
          }
        }
      } catch {
        setStatus("error");
      }
    }

    void run();
  }, [token]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex justify-end">
          <LanguageSwitcher language={language} setLanguage={setLanguage} t={t} />
        </div>

        <h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-900">
          {t("verifyEmail.heading")}
        </h1>

        {status === "verifying" ? (
          <p className="mt-3 text-sm text-slate-600" role="status">
            {t("verifyEmail.verifying")}
          </p>
        ) : null}

        {status === "missing-token" ? (
          <>
            <p className="mt-3 text-sm text-red-600" role="alert">
              {t("verifyEmail.missingToken")}
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("verifyEmail.goToLogin")}
            </Link>
          </>
        ) : null}

        {status === "error" ? (
          <>
            <p className="mt-2 text-sm font-medium text-red-700">
              {t("verifyEmail.errorTitle")}
            </p>
            <p className="mt-1 text-sm text-red-600" role="alert">
              {t("verifyEmail.errorMessage")}
            </p>
            <Link
              href="/login"
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {t("verifyEmail.goToLogin")}
            </Link>
          </>
        ) : null}

        {status === "success" ? (
          <>
            <p className="mt-2 text-sm font-medium text-emerald-700">
              {t("verifyEmail.successTitle")}
            </p>
            <p className="mt-1 text-sm text-slate-600" role="status">
              {t("verifyEmail.successMessage")}
            </p>
            <Link
              href={isAuthenticated() ? "/dashboard" : "/login"}
              className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              {isAuthenticated()
                ? t("verifyEmail.goToDashboard")
                : t("verifyEmail.goToLogin")}
            </Link>
          </>
        ) : null}
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailContent />
    </Suspense>
  );
}
