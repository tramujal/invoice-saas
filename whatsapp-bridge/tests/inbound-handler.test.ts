import { describe, expect, it } from "vitest";

import { normalizeInboundMessage, type RawMessageLike } from "../src/transport/inbound-handler.js";

describe("inbound-handler normalization", () => {
  it("normalizes a plain text message", async () => {
    const raw: RawMessageLike = {
      id: { id: "msg-1" },
      from: "59899123456@c.us",
      timestamp: 1700000000,
      body: "hola",
      hasMedia: false,
      type: "chat",
    };
    const result = await normalizeInboundMessage(raw, async () => null);
    expect(result.type).toBe("text");
    expect(result.text).toBe("hola");
    expect(result.provider).toBe("webjs");
    expect(result.phoneNumber).toBe("59899123456@c.us");
  });

  it("normalizes a voice note into an audio envelope with media", async () => {
    const raw: RawMessageLike = {
      id: { id: "msg-2" },
      from: "59899123456@c.us",
      timestamp: 1700000000,
      body: "",
      hasMedia: true,
      type: "ptt",
    };
    const base64 = Buffer.from("fake-audio").toString("base64");
    const result = await normalizeInboundMessage(raw, async () => ({ mimetype: "audio/ogg", data: base64 }));
    expect(result.type).toBe("audio");
    expect(result.media?.mimeType).toBe("audio/ogg");
    expect(result.media?.contentBase64).toBe(base64);
  });

  it("falls back to a text envelope if media download fails", async () => {
    const raw: RawMessageLike = {
      id: { id: "msg-3" },
      from: "59899123456@c.us",
      timestamp: 1700000000,
      body: "",
      hasMedia: true,
      type: "ptt",
    };
    const result = await normalizeInboundMessage(raw, async () => null);
    expect(result.type).toBe("text");
  });
});
