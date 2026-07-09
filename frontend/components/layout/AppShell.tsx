"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import {
  clearAuthSession,
  getOrganizationName,
  getUserEmail,
  isAuthenticated,
} from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";

const links = [
  { href: "/dashboard", labelKey: "nav.dashboard" },
  { href: "/invoices", labelKey: "nav.invoices" },
  { href: "/customers", labelKey: "nav.customers" },
  { href: "/settings", labelKey: "nav.settings" },
] as const;

function isNavActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const [organizationName, setOrganizationName] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }

    let cancelled = false;
    apiFetch("/auth/me").catch((err) => {
      if (!cancelled && err instanceof ApiError && err.status === 401) {
        router.replace("/login");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    // Cheap, synchronous re-read on every navigation so a rename saved on
    // /settings shows up in the sidebar without requiring a re-login.
    setOrganizationName(getOrganizationName());
    setUserEmail(getUserEmail());
  }, [pathname]);

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      <aside className="shrink-0 border-slate-200 bg-white md:w-56 md:border-r">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-4 md:block md:border-b-0 md:px-6 md:pt-6">
          <Link href="/dashboard" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 md:mt-4 md:w-full"
          >
            {t("nav.logout")}
          </button>
        </div>
        {organizationName || userEmail ? (
          <div className="hidden border-b border-slate-100 px-6 py-3 md:block">
            {organizationName ? (
              <p className="truncate text-sm font-medium text-slate-800">
                {organizationName}
              </p>
            ) : null}
            {userEmail ? (
              <p className="truncate text-xs text-slate-500">{userEmail}</p>
            ) : null}
          </div>
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
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">{children}</main>
    </div>
  );
}
