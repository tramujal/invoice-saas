"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { authRequest } from "@/lib/api";
import { isRateLimitedError } from "@/lib/format-api-error";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export default function ForgotPasswordPage() {
  const { t, language, setLanguage } = useMarketingTranslation();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError(t("auth.errorFillAllFields"));
      return;
    }

    setIsSubmitting(true);
    try {
      // The backend always returns the same generic response whether or
      // not the email exists — we just need the request to succeed. We
      // show our own translated copy of that message rather than the
      // server's (English-only) text, so this page respects the active
      // marketing-page language.
      await authRequest(defaultApi, "/auth/forgot-password", {
        email: email.trim(),
        language,
      });
      setSubmitted(true);
    } catch (err) {
      setError(
        isRateLimitedError(err)
          ? t("errors.rateLimitedPasswordReset")
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
          {t("auth.forgotPasswordHeading")}
        </h1>

        {submitted ? (
          <>
            <p className="mt-3 text-sm text-slate-600" role="status">
              {t("auth.forgotPasswordSuccessMessage")}
            </p>
            <Link
              href="/login"
              className="mt-6 inline-block text-sm font-medium text-slate-700 hover:text-slate-900"
            >
              ← {t("auth.backToLogin")}
            </Link>
          </>
        ) : (
          <>
            <p className="mt-1 text-sm text-slate-500">
              {t("auth.forgotPasswordSubtitle")}
            </p>

            <form onSubmit={onSubmit} className="mt-6 space-y-4">
              <div>
                <label
                  className="block text-xs font-medium text-slate-700"
                  htmlFor="email"
                >
                  {t("common.email")}
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={t("auth.emailPlaceholder")}
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
                {isSubmitting ? t("auth.forgotPasswordSending") : t("auth.forgotPasswordSubmit")}
              </button>

              <Link
                href="/login"
                className="block text-center text-sm font-medium text-slate-700 hover:text-slate-900"
              >
                ← {t("auth.backToLogin")}
              </Link>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
