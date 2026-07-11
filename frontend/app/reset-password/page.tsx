"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { PasswordRequirementsChecklist } from "@/components/auth/PasswordRequirementsChecklist";
import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { useToast } from "@/components/ui/toast";
import { ApiError, authRequest } from "@/lib/api";
import { formatApiError, isRateLimitedError } from "@/lib/format-api-error";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import { isPasswordValid } from "@/lib/password-policy";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

function MissingTokenState({
  t,
  language,
  setLanguage,
}: ReturnType<typeof useMarketingTranslation>) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex justify-end">
          <LanguageSwitcher language={language} setLanguage={setLanguage} t={t} />
        </div>
        <h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-900">
          {t("auth.resetPasswordHeading")}
        </h1>
        <p className="mt-3 text-sm text-red-600" role="alert">
          {t("auth.errorMissingToken")}
        </p>
        <Link
          href="/forgot-password"
          className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
        >
          {t("auth.requestNewLink")}
        </Link>
      </div>
    </div>
  );
}

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  const marketingTranslation = useMarketingTranslation();
  const { t, language, setLanguage } = marketingTranslation;
  const token = searchParams.get("token");

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!token) {
    return <MissingTokenState t={t} language={language} setLanguage={setLanguage} />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!newPassword || !confirmPassword) {
      setError(t("auth.errorFillAllFields"));
      return;
    }
    if (!isPasswordValid(newPassword)) {
      setError(t("auth.errorPasswordPolicy"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("auth.errorPasswordsDontMatch"));
      return;
    }

    setIsSubmitting(true);
    try {
      await authRequest(defaultApi, "/auth/reset-password", {
        token,
        new_password: newPassword,
      });
      toast.success(t("auth.resetPasswordSuccessToast"));
      router.replace("/login");
    } catch (err) {
      setError(
        isRateLimitedError(err)
          ? t("errors.rateLimitedPasswordReset")
          : err instanceof ApiError
            ? formatApiError(err, t("auth.errorGeneric"))
            : t("auth.errorGeneric")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex justify-end">
          <LanguageSwitcher language={language} setLanguage={setLanguage} t={t} />
        </div>

        <h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-900">
          {t("auth.resetPasswordHeading")}
        </h1>
        <p className="mt-1 text-sm text-slate-500">{t("auth.resetPasswordSubtitle")}</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="new-password"
            >
              {t("auth.newPasswordLabel")}
            </label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder={t("auth.passwordPlaceholderRegister")}
              disabled={isSubmitting}
            />
            <PasswordRequirementsChecklist password={newPassword} t={t} />
          </div>
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="confirm-password"
            >
              {t("auth.confirmPasswordLabel")}
            </label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder={t("auth.passwordPlaceholderRegister")}
              disabled={isSubmitting}
            />
          </div>

          {error ? (
            <p className="text-sm text-red-600" role="alert">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting ? t("auth.resettingPassword") : t("auth.resetPasswordSubmit")}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
