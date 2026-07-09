"use client";

import { useEffect, useState } from "react";

import {
  DEFAULT_LANGUAGE,
  normalizeLanguage,
  SUPPORTED_LANGUAGES,
  translate,
  type SupportedLanguage,
} from "@/lib/i18n/translations";

/** Deliberately separate from the organization-scoped language key
 * (auth-storage.ts) — an anonymous visitor's language choice on a public
 * page must never bleed into, or be overwritten by, an authenticated
 * organization's configured language. */
const MARKETING_LANGUAGE_KEY = "invoicing_marketing_language";

function getStoredLanguage(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(MARKETING_LANGUAGE_KEY);
}

function detectBrowserLanguage(): SupportedLanguage {
  if (typeof navigator === "undefined") return DEFAULT_LANGUAGE;
  const candidates =
    navigator.languages && navigator.languages.length > 0
      ? navigator.languages
      : [navigator.language];
  for (const candidate of candidates) {
    const primary = candidate?.split("-")[0]?.toLowerCase();
    if (primary && (SUPPORTED_LANGUAGES as readonly string[]).includes(primary)) {
      return primary as SupportedLanguage;
    }
  }
  return DEFAULT_LANGUAGE;
}

/**
 * Language source for public/marketing pages (landing page, and any future
 * marketing page): a dedicated localStorage key if the visitor has already
 * picked a language, otherwise the browser's language, otherwise English.
 *
 * Reuses the same TRANSLATIONS data and translate()/normalizeLanguage()
 * lookup logic as useTranslation() — only the language-resolution source
 * differs, since marketing pages have no organization to read a setting
 * from.
 *
 * Defaults to English on first render (including the server pre-render) and
 * only resolves the real language inside an effect, matching the
 * hydration-safe pattern used everywhere else in this app.
 */
export function useMarketingTranslation() {
  const [language, setLanguageState] = useState<SupportedLanguage>(DEFAULT_LANGUAGE);

  useEffect(() => {
    const stored = getStoredLanguage();
    setLanguageState(stored ? normalizeLanguage(stored) : detectBrowserLanguage());
  }, []);

  function setLanguage(next: SupportedLanguage) {
    setLanguageState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(MARKETING_LANGUAGE_KEY, next);
    }
  }

  function t(key: string, params?: Record<string, string | number>): string {
    return translate(language, key, params);
  }

  return { t, language, setLanguage };
}
