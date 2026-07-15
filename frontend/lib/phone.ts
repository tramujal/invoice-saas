/** Phone helpers shared by every WhatsApp/tel: touchpoint. Digits-only
 * normalization for wa.me links -- never invents or prepends a country
 * code; only the digits already present in the stored number are used. */

export function normalizePhoneForWhatsapp(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const digitsOnly = raw.replace(/[^\d]/g, "");
  return digitsOnly.length > 0 ? digitsOnly : null;
}
