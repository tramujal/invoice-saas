import { describe, expect, it } from "vitest";

import {
  InvalidBridgeSignatureError,
  signBridgeRequest,
  verifyBridgeSignature,
} from "../src/security/request-signing.js";

describe("request-signing", () => {
  it("verifies a correctly signed request", () => {
    const body = Buffer.from(JSON.stringify({ hello: "world" }));
    const ts = Math.floor(Date.now() / 1000);
    const header = signBridgeRequest("s3cret", ts, body);
    expect(() =>
      verifyBridgeSignature({ secret: "s3cret", signatureHeader: header, body, toleranceSeconds: 300 })
    ).not.toThrow();
  });

  it("rejects a tampered body", () => {
    const body = Buffer.from("original");
    const ts = Math.floor(Date.now() / 1000);
    const header = signBridgeRequest("s3cret", ts, body);
    expect(() =>
      verifyBridgeSignature({
        secret: "s3cret",
        signatureHeader: header,
        body: Buffer.from("tampered"),
        toleranceSeconds: 300,
      })
    ).toThrow(InvalidBridgeSignatureError);
  });

  it("rejects the wrong secret", () => {
    const body = Buffer.from("payload");
    const ts = Math.floor(Date.now() / 1000);
    const header = signBridgeRequest("s3cret", ts, body);
    expect(() =>
      verifyBridgeSignature({ secret: "wrong", signatureHeader: header, body, toleranceSeconds: 300 })
    ).toThrow(InvalidBridgeSignatureError);
  });

  it("rejects a stale timestamp outside the tolerance window", () => {
    const body = Buffer.from("payload");
    const staleTs = Math.floor(Date.now() / 1000) - 10_000;
    const header = signBridgeRequest("s3cret", staleTs, body);
    expect(() =>
      verifyBridgeSignature({ secret: "s3cret", signatureHeader: header, body, toleranceSeconds: 300 })
    ).toThrow(InvalidBridgeSignatureError);
  });

  it("rejects a missing signature header", () => {
    expect(() =>
      verifyBridgeSignature({
        secret: "s3cret",
        signatureHeader: undefined,
        body: Buffer.from("x"),
        toleranceSeconds: 300,
      })
    ).toThrow(InvalidBridgeSignatureError);
  });

  it("accepts any matching v1 candidate among several (secret-rotation window)", () => {
    const body = Buffer.from("payload");
    const ts = Math.floor(Date.now() / 1000);
    const validSignature = signBridgeRequest("s3cret", ts, body).split("v1=")[1];
    const header = `t=${ts},v1=deadbeef,v1=${validSignature}`;
    expect(() =>
      verifyBridgeSignature({ secret: "s3cret", signatureHeader: header, body, toleranceSeconds: 300 })
    ).not.toThrow();
  });
});
