"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { useTranslation } from "@/lib/i18n/useTranslation";

const TABS = [
  { href: "/settings", labelKey: "settingsNav.organization" },
  { href: "/settings/team", labelKey: "settingsNav.team" },
  { href: "/settings/plan", labelKey: "settingsNav.plan" },
  { href: "/settings/api-keys", labelKey: "settingsNav.apiKeys" },
  { href: "/settings/webhooks", labelKey: "settingsNav.webhooks" },
  { href: "/settings/whatsapp", labelKey: "settingsNav.whatsapp" },
  { href: "/settings/notifications", labelKey: "settingsNav.notifications" },
  { href: "/settings/audit-log", labelKey: "settingsNav.auditLog" },
] as const;

/** Kept intentionally minimal (a handful of links, no framework) rather
 * than building a general-purpose tabs component.
 *
 * Phase UX1: the 7 tab labels' combined min-content width (each is a
 * single unbreakable word/phrase, so none of them can wrap at a narrower
 * viewport) exceeds a 320-430px mobile viewport. Previously the `<nav>`
 * itself had no overflow control, so once the tabs could no longer
 * shrink to fit, their combined width overflowed the nav's own box --
 * and with nothing clipping or scrolling that overflow, it bubbled all
 * the way up to the page, forcing a full-page horizontal scrollbar on
 * every Settings page (this component is rendered at the top of every
 * one of them). Wrapping the nav in its own `overflow-x-auto` container
 * contains that scroll locally: the tab row can still be wider than the
 * viewport and scrolled horizontally, but the container itself never
 * exceeds its parent's width, so the page never does either. Desktop is
 * visually unchanged -- on a wide enough viewport the tabs already fit,
 * so the container's own scrollability never engages. */
export function SettingsSubNav() {
  const { t } = useTranslation();
  const pathname = usePathname();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const activeLinkRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    // Keeps the active tab visible within the nav's OWN horizontal
    // scroll container whenever the route changes -- adjusting
    // `scrollLeft` directly (rather than calling scrollIntoView(), which
    // can also scroll unrelated ancestor/page scroll positions) so this
    // never affects anything outside this one small strip.
    const container = scrollContainerRef.current;
    const activeLink = activeLinkRef.current;
    if (!container || !activeLink) return;

    const containerWidth = container.clientWidth;
    const linkLeft = activeLink.offsetLeft;
    const linkRight = linkLeft + activeLink.offsetWidth;

    if (linkLeft < container.scrollLeft) {
      container.scrollLeft = linkLeft;
    } else if (linkRight > container.scrollLeft + containerWidth) {
      container.scrollLeft = linkRight - containerWidth;
    }
  }, [pathname]);

  return (
    <div ref={scrollContainerRef} className="overflow-x-auto border-b border-slate-200">
      <nav className="flex w-max gap-1" aria-label={t("settingsNav.label")}>
        {TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              ref={active ? activeLinkRef : undefined}
              className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "border-slate-900 text-slate-900"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
              aria-current={active ? "page" : undefined}
            >
              {t(tab.labelKey)}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
