export const LANGUAGES = ["en", "es"] as const;
export type Language = (typeof LANGUAGES)[number];

export const LANGUAGE_LABELS: Record<Language, string> = {
  en: "English",
  es: "Español",
};

export const CURRENCY_CODES = ["USD", "UYU", "EUR"] as const;
export type CurrencyCode = (typeof CURRENCY_CODES)[number];

export const TAX_LABEL_OPTIONS = ["Tax ID", "RUT", "CUIT", "NIF"] as const;
export type TaxLabelOption = (typeof TAX_LABEL_OPTIONS)[number];
