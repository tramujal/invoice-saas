"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { clearAuthSession, getOrganizationName, isAuthenticated } from "@/lib/auth-storage";
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
  }, [pathname]);

  function logout() {
    clearAuthSession();
    router.replace("/login");
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
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">{children}</main>
    </div>
  );
}
