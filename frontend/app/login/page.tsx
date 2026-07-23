"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { PasswordRequirementsChecklist } from "@/components/auth/PasswordRequirementsChecklist";
import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError, authRequest, publicGet } from "@/lib/api";
import { formatApiError, isRateLimitedError } from "@/lib/format-api-error";
import {
  isAuthenticated,
  isPlatformAdminAuthenticated,
  setAuthSession,
} from "@/lib/auth-storage";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import { isPasswordValid } from "@/lib/password-policy";
import type { AuthResponse, PublicConfig } from "@/lib/types";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

type Mode = "login" | "register";

/** A platform-admin-only account (see app.platform_permissions) may have
 * zero organization memberships -- ordinary login/register can never
 * produce that (registration always creates exactly one organization),
 * but an account bootstrapped via the CLI grant script can. Fails only
 * when there's genuinely nothing to sign in to: no organization AND no
 * platform role. */
function applyAuthResponse(auth: AuthResponse, apiBaseUrl: string): boolean {
  const organization = auth.organizations[0];
  if (!organization && !auth.user.platform_role) return false;

  setAuthSession({
    token: auth.access_token,
    apiBaseUrl,
    organizationId: organization?.id,
    organizationName: organization?.name,
    organizationCurrency: organization?.currency_code,
    organizationLanguage: organization?.language,
    organizationPermissions: organization?.permissions,
    userEmail: auth.user.email,
    emailVerified: auth.user.email_verified,
    platformRole: auth.user.platform_role,
  });
  return true;
}

/** Only ever a same-origin relative path -- never trust the raw query
 * value as a redirect target (a "//evil.com" or absolute-URL value would
 * otherwise be a classic open-redirect). Used to send the visitor back to
 * where they came from (e.g. /accept-invitation?token=...) after signing
 * in, instead of always landing on the default. `fallback` lets the
 * caller pick /dashboard vs. /admin once the auth response is known (a
 * zero-organization platform admin has no /dashboard to land on). */
function safeNextPath(raw: string | null, fallback: string): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : fallback;
}

/** Where to land after a successful sign-in with no explicit ?next= --
 * an ordinary user (or any user with at least one organization) goes to
 * their dashboard; a platform-admin-only account with zero organizations
 * has nowhere else to go but the admin console. */
function defaultLandingPath(auth: AuthResponse): string {
  return auth.organizations[0] ? "/dashboard" : "/admin";
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
  // Defaults to enabled so the tab never flickers/hides before the
  // request resolves -- purely cosmetic either way, since the backend
  // (app.routers.auth.register) is the authoritative gate and rejects
  // with 403 registrations_disabled regardless of what this shows.
  const [registrationsEnabled, setRegistrationsEnabled] = useState(true);

  useEffect(() => {
    // Checked in this order since an account can hold both an
    // organization and a platform role -- their organization dashboard is
    // the more useful landing spot in that case, matching defaultLandingPath.
    if (isAuthenticated()) {
      router.replace(safeNextPath(searchParams.get("next"), "/dashboard"));
    } else if (isPlatformAdminAuthenticated()) {
      router.replace(safeNextPath(searchParams.get("next"), "/admin"));
    }
  }, [router, searchParams]);

  useEffect(() => {
    let cancelled = false;
    publicGet<PublicConfig>(apiBaseUrl, "/public/config")
      .then((config) => {
        if (!cancelled) setRegistrationsEnabled(config.registrations_enabled);
      })
      .catch(() => {
        // Unreachable API, wrong apiBaseUrl, etc. -- fail open on the
        // cosmetic gate; the backend still enforces the real one.
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  useEffect(() => {
    if (!registrationsEnabled && mode === "register") setMode("login");
  }, [registrationsEnabled, mode]);

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
      router.replace(safeNextPath(searchParams.get("next"), defaultLandingPath(auth)));
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
          {registrationsEnabled ? (
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
          ) : (
            <span
              className="flex-1 cursor-not-allowed rounded-md py-2 text-center text-slate-400"
              title={t("auth.registrationsDisabledNotice")}
            >
              {t("auth.createAccount")}
            </span>
          )}
        </div>

        {!registrationsEnabled ? (
          <p className="mt-3 text-xs text-slate-500">{t("auth.registrationsDisabledNotice")}</p>
        ) : null}

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
