import type { TranslateFn } from "@/lib/i18n/useTranslation";

export const PRODUCT_TYPES = ["product", "service"] as const;

export type ProductType = (typeof PRODUCT_TYPES)[number];

export function isProductType(value: string): value is ProductType {
  return (PRODUCT_TYPES as readonly string[]).includes(value);
}

/** Looks up the translated label for a product type. Takes the caller's
 * own t() (from useTranslation()) rather than calling the hook itself, so
 * this stays a plain, hook-free utility module — same convention as
 * lib/payment-status.ts's getPaymentStatusLabel. */
export function getProductTypeLabel(t: TranslateFn, type: ProductType): string {
  return t(`products.type.${type}`);
}

export const PRODUCT_TYPE_BADGE_CLASS: Record<ProductType, string> = {
  product: "bg-sky-100 text-sky-900 ring-sky-200/80",
  service: "bg-violet-100 text-violet-900 ring-violet-200/80",
};
