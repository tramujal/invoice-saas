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
