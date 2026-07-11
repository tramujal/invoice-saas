"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api";
import {
  clearAuthSession,
  EMAIL_VERIFIED_STORAGE_KEY,
  getEmailVerified,
  getOrganizationName,
  isAuthenticated,
  setEmailVerified as cacheEmailVerified,
} from "@/lib/auth-storage";
import { formatApiError, isRateLimitedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { MeResponse, MessageResponse } from "@/lib/types";

const links = [
  { href: "/dashboard", labelKey: "nav.dashboard" },
  { href: "/invoices", labelKey: "nav.invoices" },
  { href: "/customers", labelKey: "nav.customers" },
  { href: "/assistant", labelKey: "nav.assistant" },
  { href: "/settings", labelKey: "nav.settings" },
] as const;

function isNavActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();
  const [organizationName, setOrganizationName] = useState<string | null>(null);
  // Hydration-safe default (see getOrganizationName below for the same
  // pattern): assume verified until the first /auth/me response actually
  // says otherwise, so the banner never flashes on a verified account.
  const [emailVerified, setEmailVerifiedState] = useState(true);
  const [isResending, setIsResending] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }

    let cancelled = false;
    apiFetch<MeResponse>("/auth/me")
      .then((me) => {
        if (cancelled) return;
        setEmailVerifiedState(me.user.email_verified);
        cacheEmailVerified(me.user.email_verified);
      })
      .catch((err) => {
        if (!cancelled && err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router, pathname]);

  useEffect(() => {
    // Cheap, synchronous re-read on every navigation so a rename saved on
    // /settings shows up in the sidebar without requiring a re-login.
    setOrganizationName(getOrganizationName());
    setEmailVerifiedState(getEmailVerified());
  }, [pathname]);

  useEffect(() => {
    // Cross-tab sync: if verification completes on /verify-email in a
    // *different* tab of this same browser, that page writes the new value
    // to localStorage, which fires this `storage` event here — so the
    // banner disappears in this tab immediately, with no navigation or
    // manual refresh needed in this tab at all.
    function onStorage(e: StorageEvent) {
      if (e.key === EMAIL_VERIFIED_STORAGE_KEY) {
        setEmailVerifiedState(getEmailVerified());
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  async function resendVerification() {
    if (isResending) return;
    setIsResending(true);
    try {
      const result = await apiFetch<MessageResponse>("/auth/resend-verification", {
        method: "POST",
      });
      toast.success(result.message || t("emailBanner.resendSuccess"));
    } catch (err) {
      toast.error(
        isRateLimitedError(err)
          ? t("errors.rateLimitedVerification")
          : formatApiError(err, t("emailBanner.resendError"))
      );
    } finally {
      setIsResending(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      <aside className="flex shrink-0 flex-col border-slate-200 bg-white md:w-56 md:border-r">
        <div className="border-b border-slate-200 px-4 py-4 md:border-b-0 md:px-6 md:pt-6">
          <Link href="/dashboard" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
        </div>
        {organizationName ? (
          <Link
            href="/settings"
            className="hidden truncate border-b border-slate-100 px-6 py-3 text-sm font-semibold text-slate-800 hover:bg-surface-muted md:block"
          >
            {organizationName}
          </Link>
        ) : null}
        <nav className="flex gap-1 overflow-x-auto px-2 pb-3 md:flex-col md:px-2 md:pb-6">
          {links.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition md:px-4 ${
                  active
                    ? "bg-slate-900 text-white"
                    : "text-slate-700 hover:bg-surface-muted"
                }`}
              >
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-slate-200 px-4 py-3 md:mt-auto md:px-6 md:pb-6">
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            {t("nav.logout")}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">
        {!emailVerified ? (
          <div
            role="status"
            className="mb-4 flex flex-col items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between"
          >
            <p>{t("emailBanner.message")}</p>
            <button
              type="button"
              onClick={() => void resendVerification()}
              disabled={isResending}
              className="shrink-0 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isResending ? t("emailBanner.resendSending") : t("emailBanner.resendAction")}
            </button>
          </div>
        ) : null}
        {children}
      </main>
    </div>
  );
}
