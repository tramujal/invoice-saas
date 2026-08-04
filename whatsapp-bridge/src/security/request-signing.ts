/**
 * HMAC request signing/verification -- mirrors the Python backend's
 * app/whatsapp/security.py EXACTLY (same canonical string
 * "{timestamp}.{raw_body}", same "t=<ts>,v1=<hex>" header shape, same
 * constant-time comparison, same tolerance-window replay protection).
 * Used in both directions: this bridge signs requests it sends to the
 * backend, and verifies requests the backend sends to it.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

export const SIGNATURE_HEADER = "x-whatsapp-bridge-signature";

export class InvalidBridgeSignatureError extends Error {}

export function signBridgeRequest(secret: string, timestampSeconds: number, body: Buffer): string {
  const signedString = Buffer.concat([Buffer.from(`${timestampSeconds}.`, "ascii"), body]);
  const signature = createHmac("sha256", secret).update(signedString).digest("hex");
  return `t=${timestampSeconds},v1=${signature}`;
}

export function verifyBridgeSignature(params: {
  secret: string;
  signatureHeader: string | undefined;
  body: Buffer;
  toleranceSeconds: number;
}): void {
  const { secret, signatureHeader, body, toleranceSeconds } = params;
  if (!signatureHeader) {
    throw new InvalidBridgeSignatureError("Missing signature header.");
  }

  let timestamp: number | null = null;
  const signatures: string[] = [];
  for (const part of signatureHeader.split(",")) {
    const eqIndex = part.indexOf("=");
    if (eqIndex === -1) continue;
    const key = part.slice(0, eqIndex).trim();
    const value = part.slice(eqIndex + 1).trim();
    if (key === "t") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isNaN(parsed)) {
        throw new InvalidBridgeSignatureError("Malformed timestamp in signature header.");
      }
      timestamp = parsed;
    } else if (key === "v1") {
      signatures.push(value);
    }
  }

  if (timestamp === null || signatures.length === 0) {
    throw new InvalidBridgeSignatureError("Malformed signature header.");
  }

  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - timestamp) > toleranceSeconds) {
    throw new InvalidBridgeSignatureError("Signature timestamp is outside the tolerance window.");
  }

  const signedString = Buffer.concat([Buffer.from(`${timestamp}.`, "ascii"), body]);
  const expected = createHmac("sha256", secret).update(signedString).digest("hex");
  const expectedBuffer = Buffer.from(expected, "utf8");

  const matches = signatures.some((candidate) => {
    const candidateBuffer = Buffer.from(candidate, "utf8");
    // timingSafeEqual throws if lengths differ -- an attacker-controlled
    // candidate of the wrong length must never throw an exception that
    // could behave differently from "no match" in a way that's
    // observable; catch and treat as non-matching.
    if (candidateBuffer.length !== expectedBuffer.length) return false;
    return timingSafeEqual(expectedBuffer, candidateBuffer);
  });

  if (!matches) {
    throw new InvalidBridgeSignatureError("Signature does not match.");
  }
}
