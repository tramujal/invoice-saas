import { describe, expect, it } from "vitest";

import { AudioTooLargeError, toDownloadedMedia } from "../src/media/audio-handler.js";

describe("audio-handler", () => {
  it("converts a raw media object into a normalized DownloadedMedia", () => {
    const base64 = Buffer.from("small audio payload").toString("base64");
    const result = toDownloadedMedia({ mimetype: "audio/ogg; codecs=opus", data: base64 });
    expect(result.mimeType).toBe("audio/ogg; codecs=opus");
    expect(result.contentBase64).toBe(base64);
    expect(result.sizeBytes).toBeGreaterThan(0);
  });

  it("rejects media larger than the configured maximum", () => {
    const huge = Buffer.alloc(6 * 1024 * 1024).toString("base64"); // 6 MB > default 5 MB cap
    expect(() => toDownloadedMedia({ mimetype: "audio/ogg", data: huge })).toThrow(AudioTooLargeError);
  });
});
