"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useTranslation } from "@/lib/i18n/useTranslation";

const TABS = [
  { href: "/settings", labelKey: "settingsNav.organization" },
  { href: "/settings/team", labelKey: "settingsNav.team" },
] as const;

/** The only tab UI this page has ever had -- kept intentionally minimal
 * (2 links, no framework) rather than building a general-purpose tabs
 * component for a settings page that has no other sub-sections planned. */
export function SettingsSubNav() {
  const { t } = useTranslation();
  const pathname = usePathname();

  return (
    <nav className="flex gap-1 border-b border-slate-200" aria-label={t("settingsNav.label")}>
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
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
  );
}
