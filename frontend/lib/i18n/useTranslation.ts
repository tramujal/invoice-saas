"use client";

import { useEffect, useState } from "react";

import { getOrganizationLanguage } from "@/lib/auth-storage";
import {
  DEFAULT_LANGUAGE,
  normalizeLanguage,
  translate,
  type SupportedLanguage,
} from "@/lib/i18n/translations";

/** Shared type for a resolved t() function, so utility modules that need to
 * accept a translator (e.g. lib/payment-status.ts) don't redeclare this
 * signature or import the hook themselves. */
export type TranslateFn = (
  key: string,
  params?: Record<string, string | number>
) => string;

/**
 * Reads the active language and returns a t(key, params?) function.
 *
 * Defaults to English on first render (including the server pre-render) and
 * only reads the real value from localStorage inside an effect — reading it
 * in a useState initializer would run during SSR too, where it's
 * unavailable, and produce a server/client text mismatch.
 */
export function useTranslation() {
  const [language, setLanguage] = useState<SupportedLanguage>(DEFAULT_LANGUAGE);

  useEffect(() => {
    setLanguage(normalizeLanguage(getOrganizationLanguage()));
  }, []);

  function t(key: string, params?: Record<string, string | number>): string {
    return translate(language, key, params);
  }

  return { t, language };
}
