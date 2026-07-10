"use client";

import type { TranslateFn } from "@/lib/i18n/useTranslation";

/** Dashboard revenue currency toggle. Visually matches the marketing
 * LanguageSwitcher pill pattern, but the option list is passed in by the
 * caller (whatever currencies are actually present in this organization's
 * data) rather than a fixed constant — so it scales to any number of
 * currencies without code changes here. */
export function CurrencySelector({
  currencies,
  selected,
  onSelect,
  t,
}: {
  currencies: string[];
  selected: string;
  onSelect: (next: string) => void;
  t: TranslateFn;
}) {
  if (currencies.length <= 1) return null;

  return (
    <div
      className="flex gap-1 rounded-lg bg-slate-100 p-1 text-xs font-medium"
      role="group"
      aria-label={t("common.currencyLabel")}
    >
      {currencies.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => onSelect(code)}
          aria-pressed={selected === code}
          className={`rounded-md px-2.5 py-1.5 uppercase transition ${
            selected === code
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
