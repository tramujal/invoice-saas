/** Money helpers aligned with two-decimal currency rounding. */

export function roundMoney(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export function parseQuantity(raw: string): number | null {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

export function parseUnitPrice(raw: string): number | null {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return null;
  return roundMoney(n);
}

export function formatMoney(value: number): string {
  return roundMoney(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Single source of truth for displaying a monetary amount together with
 * its currency code, e.g. "USD 1,234.56". Every screen that shows a
 * currency-tagged amount (invoice list, invoice creation, dashboard, etc.)
 * should go through this instead of concatenating `${code} ${amount}`
 * manually, so formatting stays identical everywhere and only needs to
 * change in one place. `amount` accepts the string totals the API returns
 * (e.g. "50.00") as well as plain numbers. */
export function formatCurrency(
  amount: number | string,
  currencyCode: string
): string {
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  return `${currencyCode} ${formatMoney(value)}`;
}
