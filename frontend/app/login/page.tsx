"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { PasswordRequirementsChecklist } from "@/components/auth/PasswordRequirementsChecklist";
import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError, authRequest } from "@/lib/api";
import { formatApiError, isRateLimitedError } from "@/lib/format-api-error";
import { isAuthenticated, setAuthSession } from "@/lib/auth-storage";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import { isPasswordValid } from "@/lib/password-policy";
import type { AuthResponse } from "@/lib/types";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

type Mode = "login" | "register";

function applyAuthResponse(auth: AuthResponse, apiBaseUrl: string): boolean {
  const organization = auth.organizations[0];
  if (!organization) return false;

  setAuthSession({
    token: auth.access_token,
    apiBaseUrl,
    organizationId: organization.id,
    organizationName: organization.name,
    organizationCurrency: organization.currency_code,
    organizationLanguage: organization.language,
    organizationPermissions: organization.permissions,
    userEmail: auth.user.email,
    emailVerified: auth.user.email_verified,
  });
  return true;
}

/** Only ever a same-origin relative path -- never trust the raw query
 * value as a redirect target (a "//evil.com" or absolute-URL value would
 * otherwise be a classic open-redirect). Used to send the visitor back to
 * where they came from (e.g. /accept-invitation?token=...) after signing
 * in, instead of always landing on /dashboard. */
function safeNextPath(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/dashboard";
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t, language, setLanguage } = useMarketingTranslation();
  const [mode, setMode] = useState<Mode>(
    searchParams.get("mode") === "register" ? "register" : "login"
  );
  const [apiBaseUrl, setApiBaseUrl] = useState(defaultApi);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const nextPath = safeNextPath(searchParams.get("next"));

  useEffect(() => {
    if (isAuthenticated()) router.replace(nextPath);
  }, [router, nextPath]);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!apiBaseUrl.trim() || !email.trim() || !password) {
      setError(t("auth.errorFillAllFields"));
      return;
    }
    if (mode === "register" && !organizationName.trim()) {
      setError(t("auth.errorOrganizationNameRequired"));
      return;
    }
    if (mode === "register" && !isPasswordValid(password)) {
      setError(t("auth.errorPasswordPolicy"));
      return;
    }

    setIsSubmitting(true);
    try {
      const auth =
        mode === "login"
          ? await authRequest<AuthResponse>(apiBaseUrl, "/auth/login", {
              email: email.trim(),
              password,
            })
          : await authRequest<AuthResponse>(apiBaseUrl, "/auth/register", {
              email: email.trim(),
              password,
              organization_name: organizationName.trim(),
              language,
            });

      if (!applyAuthResponse(auth, apiBaseUrl)) {
        setError(t("auth.errorNoOrganization"));
        return;
      }
      router.replace(nextPath);
    } catch (err) {
      if (isRateLimitedError(err)) {
        setError(
          mode === "login"
            ? t("errors.rateLimitedLogin")
            : t("errors.rateLimitedRegister")
        );
      } else {
        setError(
          err instanceof ApiError
            ? formatApiError(
                err,
                mode === "login" ? t("auth.errorSignInFailed") : t("auth.errorRegisterFailed")
              )
            : t("auth.errorGeneric")
        );
      }
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

        <div className="mt-4 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm font-medium">
          <button
            type="button"
            onClick={() => switchMode("login")}
            className={`flex-1 rounded-md py-2 transition ${
              mode === "login"
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t("auth.signIn")}
          </button>
          <button
            type="button"
            onClick={() => switchMode("register")}
            className={`flex-1 rounded-md py-2 transition ${
              mode === "register"
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t("auth.createAccount")}
          </button>
        </div>

        <h1 className="mt-6 text-xl font-semibold tracking-tight text-slate-900">
          {mode === "login" ? t("auth.signIn") : t("auth.headingRegister")}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {mode === "login" ? t("auth.subtitleSignIn") : t("auth.subtitleRegister")}
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="email"
            >
              {t("common.email")}
            </label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              className="mt-1"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("auth.emailPlaceholder")}
              disabled={isSubmitting}
            />
          </div>
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="password"
            >
              {t("auth.passwordLabel")}
            </label>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              className="mt-1"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? t("auth.passwordPlaceholderRegister") : "••••••••"}
              disabled={isSubmitting}
            />
            {mode === "login" ? (
              <Link
                href="/forgot-password"
                className="mt-1.5 inline-block text-xs font-medium text-slate-500 hover:text-slate-700"
              >
                {t("auth.forgotPasswordLink")}
              </Link>
            ) : (
              <PasswordRequirementsChecklist password={password} t={t} />
            )}
          </div>

          {mode === "register" ? (
            <div>
              <label
                className="block text-xs font-medium text-slate-700"
                htmlFor="organizationName"
              >
                {t("auth.organizationNameLabel")}
              </label>
              <Input
                id="organizationName"
                type="text"
                autoComplete="organization"
                className="mt-1"
                value={organizationName}
                onChange={(e) => setOrganizationName(e.target.value)}
                placeholder={t("auth.organizationNamePlaceholder")}
                disabled={isSubmitting}
              />
            </div>
          ) : null}

          <details className="group text-xs text-slate-500">
            <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-800">
              {t("auth.advancedSummary")}
            </summary>
            <Input
              type="url"
              autoComplete="off"
              className="mt-2"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000"
              disabled={isSubmitting}
            />
          </details>

          {error ? (
            <p className="text-sm text-red-600" role="alert">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting
              ? mode === "login"
                ? t("auth.signingIn")
                : t("auth.creatingAccount")
              : mode === "login"
                ? t("auth.signIn")
                : t("auth.createAccount")}
          </Button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
