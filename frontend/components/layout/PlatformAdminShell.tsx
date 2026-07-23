"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import {
  clearAuthSession,
  getAuthToken,
  getPlatformRole,
  getUserEmail,
  updatePlatformRole,
} from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { MeResponse } from "@/lib/types";

const links = [
  { href: "/admin", labelKey: "adminNav.dashboard" },
  { href: "/admin/organizations", labelKey: "adminNav.organizations" },
  { href: "/admin/users", labelKey: "adminNav.users" },
  { href: "/admin/system-health", labelKey: "adminNav.systemHealth" },
  { href: "/admin/audit-log", labelKey: "adminNav.auditLog" },
  { href: "/admin/settings", labelKey: "adminNav.settings" },
] as const;

function isNavActive(pathname: string, href: string): boolean {
  // The root link (/admin, the Dashboard) must only match exactly --
  // every other admin route also starts with "/admin/", which would
  // otherwise keep "Dashboard" highlighted everywhere.
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The platform-administration equivalent of AppShell -- a completely
 * separate shell, deliberately not reusing AppShell, since that
 * component's auth gate (isAuthenticated()) and org switcher both
 * require an active organization, which a platform-admin-only account
 * (zero organization memberships) never has. See lib/auth-storage.ts's
 * isPlatformAdminAuthenticated()/getPlatformRole() for the parallel,
 * org-independent authorization axis this shell gates on. */
export function PlatformAdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [hasOrganizations, setHasOrganizations] = useState(false);
  const [ready, setReady] = useState(false);

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [panelVisible, setPanelVisible] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const hamburgerButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // No token at all -- not signed in to anything.
    if (!getAuthToken()) {
      router.replace("/login");
      return;
    }
    // Signed in, but no cached platform role -- an ordinary organization
    // user landed here directly; send them to their own dashboard rather
    // than bouncing an already-authenticated person to /login.
    if (!getPlatformRole()) {
      router.replace("/dashboard");
      return;
    }

    let cancelled = false;
    apiFetch<MeResponse>("/auth/me")
      .then((me) => {
        if (cancelled) return;
        // Keeps the cached role current, including a revocation that
        // happened mid-session (see updatePlatformRole's own docstring).
        updatePlatformRole(me.user.platform_role);
        if (!me.user.platform_role) {
          router.replace("/dashboard");
          return;
        }
        setUserEmail(me.user.email);
        setHasOrganizations(me.organizations.length > 0);
        setReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router, pathname]);

  useEffect(() => {
    setUserEmail(getUserEmail());
  }, [pathname]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    function handleClose() {
      setMobileNavOpen(false);
    }
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  useEffect(() => {
    if (!mobileNavOpen) {
      setPanelVisible(false);
      return;
    }
    const raf = requestAnimationFrame(() => setPanelVisible(true));
    return () => cancelAnimationFrame(raf);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    dialogRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  function openMobileNav() {
    dialogRef.current?.showModal();
    setMobileNavOpen(true);
  }

  function closeMobileNav() {
    dialogRef.current?.close();
    hamburgerButtonRef.current?.focus();
  }

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  function renderNavContent(onNavigate?: () => void) {
    return (
      <>
        <div className="border-b border-slate-100 px-6 py-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white">
            {t("adminNav.badge")}
          </span>
        </div>
        <nav className="flex flex-col gap-1 px-2 py-3 md:py-6">
          {links.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                className={`whitespace-nowrap rounded-r-lg border-l-2 py-2 pl-[14px] pr-4 text-sm font-medium transition ${
                  active
                    ? "border-slate-900 bg-slate-100 text-slate-900"
                    : "border-transparent text-slate-700 hover:bg-surface-muted"
                }`}
              >
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto border-t border-slate-200 px-4 py-3 md:px-6 md:py-4">
          {userEmail ? (
            <p className="mb-2 truncate text-sm font-medium text-slate-800">{userEmail}</p>
          ) : null}
          {hasOrganizations ? (
            <Link
              href="/dashboard"
              onClick={onNavigate}
              className="mb-2 block w-full rounded-lg border border-slate-200 px-3 py-1.5 text-center text-xs font-medium text-slate-700 transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
            >
              {t("adminNav.returnToOrganization")}
            </Link>
          ) : null}
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
          >
            {t("nav.logout")}
          </button>
        </div>
      </>
    );
  }

  // The cached platform_role (read synchronously above, before /auth/me
  // even resolves) is NEVER treated as authoritative -- it only decides
  // where to redirect a visitor who isn't a platform admin at all. Actual
  // admin chrome/content, and the child page's own data fetch, are gated
  // exclusively on `ready`, which only becomes true after the live
  // /auth/me response confirms a platform_role. `children` is not
  // rendered into the tree below this line, so the child page component
  // never mounts -- and therefore never fires its own /admin/* fetch --
  // until that server round-trip has completed. Every /admin/* endpoint
  // still independently re-checks require_platform_permission server-side
  // regardless of anything the frontend does; this gate is a UX nicety
  // (avoiding a flash of admin chrome for a visitor about to be
  // redirected), never a security boundary.
  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-surface" role="status">
        <span className="sr-only">{t("adminNav.verifyingAccess")}</span>
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" aria-hidden />
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <Link href="/admin" className="text-lg font-semibold text-slate-900">
          {t("adminNav.badge")}
        </Link>
        <button
          ref={hamburgerButtonRef}
          type="button"
          onClick={openMobileNav}
          aria-label={t("nav.openMenu")}
          className="rounded-lg p-2 text-slate-700 hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden
          >
            <path d="M3 6h18M3 12h18M3 18h18" />
          </svg>
        </button>
      </div>

      <dialog
        ref={dialogRef}
        aria-label={t("nav.mobileMenuLabel")}
        onClick={(e) => {
          if (e.target === dialogRef.current) closeMobileNav();
        }}
        className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-72 max-w-[85%] border-0 bg-transparent p-0 backdrop:bg-slate-900/40 md:hidden"
      >
        <div
          className={`flex h-full flex-col bg-white shadow-xl transition-transform duration-200 motion-reduce:transition-none ${
            panelVisible ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-4">
            <span className="text-lg font-semibold text-slate-900">{t("adminNav.badge")}</span>
            <button
              type="button"
              onClick={closeMobileNav}
              aria-label={t("nav.closeMenu")}
              className="rounded-lg p-2 text-slate-700 hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                aria-hidden
              >
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </svg>
            </button>
          </div>
          <div className="flex flex-1 flex-col overflow-y-auto">{renderNavContent(closeMobileNav)}</div>
        </div>
      </dialog>

      <aside className="hidden shrink-0 flex-col border-slate-200 bg-white md:flex md:w-56 md:border-r">
        <div className="px-6 pt-6">
          <Link href="/admin" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
        </div>
        {renderNavContent()}
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">{children}</main>
    </div>
  );
}
