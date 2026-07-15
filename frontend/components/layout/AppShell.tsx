"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api";
import {
  clearAuthSession,
  EMAIL_VERIFIED_STORAGE_KEY,
  getEmailVerified,
  getOrganizationId,
  getOrganizationName,
  isAuthenticated,
  setEmailVerified as cacheEmailVerified,
  updateActiveOrganization,
} from "@/lib/auth-storage";
import { formatApiError, isRateLimitedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { MeResponse, MessageResponse, OrganizationSummary } from "@/lib/types";

const links = [
  { href: "/dashboard", labelKey: "nav.dashboard" },
  { href: "/invoices", labelKey: "nav.invoices" },
  { href: "/quotes", labelKey: "nav.quotes" },
  { href: "/customers", labelKey: "nav.customers" },
  { href: "/products", labelKey: "nav.products" },
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
  // The full membership list -- needed to render a switcher at all (a
  // single-org user just sees their org name, same as before this
  // feature). Populated from the same /auth/me call the email-verified
  // check already makes, rather than a second request.
  const [organizations, setOrganizations] = useState<OrganizationSummary[] | null>(null);
  const [isSwitchingOrg, setIsSwitchingOrg] = useState(false);

  // Mobile off-canvas nav -- a native <dialog> (via showModal/close) gets
  // focus-trapping, Escape-to-close, and focus-return to the triggering
  // button for free, straight from the browser, with no hand-rolled
  // focus-trap or keydown-listener code needed.
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  // Starts false so the panel's first paint is off-screen (translate-x
  // applied), then flips true one frame later so the browser has two
  // distinct states to interpolate a slide-in transition between --
  // toggling the class immediately on open wouldn't animate at all.
  const [panelVisible, setPanelVisible] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const hamburgerButtonRef = useRef<HTMLButtonElement>(null);

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
        setOrganizations(me.organizations);
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

  // Syncs React state from the dialog's own native 'close' event -- this
  // fires whether the dialog closed via our button, a backdrop click, or
  // the browser's built-in Escape handling, so this is the single place
  // mobileNavOpen ever gets set back to false.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    function handleClose() {
      setMobileNavOpen(false);
    }
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  // Flips one frame after open so the panel's transform transition has a
  // "before" state to animate from (see panelVisible's declaration).
  useEffect(() => {
    if (!mobileNavOpen) {
      setPanelVisible(false);
      return;
    }
    const raf = requestAnimationFrame(() => setPanelVisible(true));
    return () => cancelAnimationFrame(raf);
  }, [mobileNavOpen]);

  // Background scroll lock while the panel is open -- showModal() already
  // blocks interaction with the rest of the page, but doesn't reliably
  // prevent background scroll (e.g. via touch) in every browser.
  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileNavOpen]);

  // Closes the panel on navigation -- a link tap inside it should never
  // leave it open underneath the newly-loaded page.
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
    // A native <dialog> is supposed to restore focus to whatever had it
    // before showModal() on its own, but that's only reliable when the
    // dialog was opened via a genuine, trusted user gesture -- explicitly
    // re-focusing the trigger here guarantees it regardless.
    hamburgerButtonRef.current?.focus();
  }

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  function switchOrganization(organizationId: string) {
    if (isSwitchingOrg || organizationId === getOrganizationId()) return;
    const target = organizations?.find((o) => o.id === organizationId);
    if (!target) return;
    setIsSwitchingOrg(true);
    updateActiveOrganization({
      organizationId: target.id,
      organizationName: target.name,
      organizationCurrency: target.currency_code,
      organizationLanguage: target.language,
    });
    // A full reload, not a client-side navigation -- every already-loaded
    // page's React state (invoice lists, dashboard totals, etc.) was
    // fetched for the *previous* organization and has no reason to
    // reactively refetch just because localStorage changed underneath it.
    window.location.assign("/dashboard");
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

  // Shared between the always-visible desktop sidebar and the mobile
  // off-canvas panel below -- one source of markup, rendered twice (once
  // per breakpoint's container), rather than hand-maintaining two copies.
  // idPrefix keeps the two simultaneously-present <select> instances'
  // DOM ids unique.
  function renderNavContent(idPrefix: string, onNavigate?: () => void) {
    return (
      <>
        {organizations && organizations.length > 1 ? (
          <div className="border-b border-slate-100 px-6 py-3">
            <label htmlFor={`${idPrefix}-org-switcher`} className="sr-only">
              {t("nav.switchOrganization")}
            </label>
            <select
              id={`${idPrefix}-org-switcher`}
              value={getOrganizationId() ?? ""}
              onChange={(e) => switchOrganization(e.target.value)}
              disabled={isSwitchingOrg}
              className="w-full truncate rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-semibold text-slate-800 outline-none ring-slate-400 focus:ring-2 disabled:opacity-60"
            >
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
        ) : organizationName ? (
          <Link
            href="/settings"
            onClick={onNavigate}
            className="truncate border-b border-slate-100 px-6 py-3 text-sm font-semibold text-slate-800 hover:bg-surface-muted"
          >
            {organizationName}
          </Link>
        ) : null}
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
        <div className="mt-auto border-t border-slate-200 px-4 py-3 md:px-6 md:pb-6">
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            {t("nav.logout")}
          </button>
        </div>
      </>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      {/* Mobile top bar -- the desktop sidebar below is hidden entirely
          below md, replaced by this bar plus the off-canvas panel. */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <Link href="/dashboard" className="text-lg font-semibold text-slate-900">
          Invoicing
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

      {/* Mobile off-canvas panel. A native <dialog> gets focus-trapping,
          Escape-to-close, and focus-return to the trigger button straight
          from the browser -- no hand-rolled equivalents needed. Styled as
          a left-edge sliding drawer rather than the browser's default
          centered box. */}
      <dialog
        ref={dialogRef}
        aria-label={t("nav.mobileMenuLabel")}
        onClick={(e) => {
          // A click that lands on the dialog element itself (not a
          // descendant) is a click on the ::backdrop -- see MDN's
          // documented pattern for click-outside-to-close on <dialog>.
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
            <span className="text-lg font-semibold text-slate-900">Invoicing</span>
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
          <div className="flex flex-1 flex-col overflow-y-auto">
            {renderNavContent("mobile", closeMobileNav)}
          </div>
        </div>
      </dialog>

      {/* Desktop sidebar -- unchanged in substance from before this pass,
          just now hidden below md instead of also rendering (differently
          styled) on mobile. */}
      <aside className="hidden shrink-0 flex-col border-slate-200 bg-white md:flex md:w-56 md:border-r">
        <div className="px-6 pt-6">
          <Link href="/dashboard" className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
        </div>
        {renderNavContent("desktop")}
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
