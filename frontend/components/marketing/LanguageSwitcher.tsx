"use client";

import { SUPPORTED_LANGUAGES, type SupportedLanguage } from "@/lib/i18n/translations";
import type { TranslateFn } from "@/lib/i18n/useTranslation";

/** Shared EN/ES toggle for public/marketing pages (landing page, login page,
 * and any future marketing page). Pair with useMarketingTranslation() —
 * language and setLanguage come from that hook, not from the
 * organization-scoped useTranslation(). */
export function LanguageSwitcher({
  language,
  setLanguage,
  t,
}: {
  language: SupportedLanguage;
  setLanguage: (next: SupportedLanguage) => void;
  t: TranslateFn;
}) {
  return (
    <div
      className="flex gap-1 rounded-lg bg-slate-100 p-1 text-xs font-medium"
      role="group"
      aria-label={t("common.languageAriaLabel")}
    >
      {SUPPORTED_LANGUAGES.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLanguage(code)}
          aria-pressed={language === code}
          className={`rounded-md px-2.5 py-1.5 uppercase transition ${
            language === code
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {code}
        </button>
      ))}
    </div>
  );
}
