"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, authRequest } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { isAuthenticated, setAuthSession } from "@/lib/auth-storage";
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
    userEmail: auth.user.email,
  });
  return true;
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [apiBaseUrl, setApiBaseUrl] = useState(defaultApi);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthenticated()) router.replace("/");
  }, [router]);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!apiBaseUrl.trim() || !email.trim() || !password) {
      setError("Please fill in all fields.");
      return;
    }
    if (mode === "register" && !organizationName.trim()) {
      setError("Please enter an organization name.");
      return;
    }
    if (mode === "register" && password.length < 8) {
      setError("Password must be at least 8 characters.");
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
            });

      if (!applyAuthResponse(auth, apiBaseUrl)) {
        setError("No organization found for this account.");
        return;
      }
      router.replace("/");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? formatApiError(
              err,
              mode === "login" ? "Could not sign in." : "Could not create account."
            )
          : "Something went wrong. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1 text-sm font-medium">
          <button
            type="button"
            onClick={() => switchMode("login")}
            className={`flex-1 rounded-md py-2 transition ${
              mode === "login"
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            Sign in
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
            Create account
          </button>
        </div>

        <h1 className="mt-6 text-xl font-semibold tracking-tight text-slate-900">
          {mode === "login" ? "Sign in" : "Create your organization"}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {mode === "login"
            ? "Sign in with your email and password."
            : "This creates your account and a new organization."}
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="email"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              disabled={isSubmitting}
            />
          </div>
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="password"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "At least 8 characters" : "••••••••"}
              disabled={isSubmitting}
            />
          </div>

          {mode === "register" ? (
            <div>
              <label
                className="block text-xs font-medium text-slate-700"
                htmlFor="organizationName"
              >
                Organization name
              </label>
              <input
                id="organizationName"
                type="text"
                autoComplete="organization"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                value={organizationName}
                onChange={(e) => setOrganizationName(e.target.value)}
                placeholder="Acme Inc."
                disabled={isSubmitting}
              />
            </div>
          ) : null}

          <details className="group text-xs text-slate-500">
            <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-800">
              Advanced: API base URL
            </summary>
            <input
              type="url"
              autoComplete="off"
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
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

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting
              ? mode === "login"
                ? "Signing in…"
                : "Creating account…"
              : mode === "login"
                ? "Sign in"
                : "Create account"}
          </button>
        </form>
      </div>
    </div>
  );
}
