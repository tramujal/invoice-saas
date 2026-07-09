"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { clearAuthSession, isAuthenticated } from "@/lib/auth-storage";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/invoices", label: "Invoices" },
  { href: "/customers", label: "Customers" },
] as const;

function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated()) router.replace("/login");
  }, [router]);

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      <aside className="shrink-0 border-slate-200 bg-white md:w-56 md:border-r">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-4 md:block md:border-b-0 md:px-6 md:pt-6">
          <Link href="/" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 md:mt-4 md:w-full"
          >
            Log out
          </button>
        </div>
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
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">{children}</main>
    </div>
  );
}
