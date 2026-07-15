import { describe, expect, it } from "vitest";

import { normalizePhoneForWhatsapp } from "./phone";

describe("normalizePhoneForWhatsapp", () => {
  it("strips +, spaces, -, ., ( and ) and keeps digits only", () => {
    expect(normalizePhoneForWhatsapp("+1 (555) 123-4567")).toBe("15551234567");
    expect(normalizePhoneForWhatsapp("555.123.4567")).toBe("5551234567");
  });

  it("never invents or prepends a country code", () => {
    // A locally-formatted number with no country code stays exactly as
    // stored, digits-only -- normalizePhoneForWhatsapp must never guess one.
    expect(normalizePhoneForWhatsapp("5551234567")).toBe("5551234567");
  });

  it("returns null for missing or empty input", () => {
    expect(normalizePhoneForWhatsapp(null)).toBeNull();
    expect(normalizePhoneForWhatsapp(undefined)).toBeNull();
    expect(normalizePhoneForWhatsapp("")).toBeNull();
  });

  it("returns null when nothing but symbols/whitespace remain", () => {
    expect(normalizePhoneForWhatsapp("   ")).toBeNull();
    expect(normalizePhoneForWhatsapp("(-.)")).toBeNull();
  });
});
