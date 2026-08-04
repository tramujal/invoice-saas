/**
 * Normalizes a raw whatsapp-web.js message event into the shared
 * NormalizedInboundMessage envelope -- the one place this bridge
 * translates a provider-specific object into the provider-agnostic shape
 * every other module (backend-client, the future Meta Cloud API adapter)
 * depends on instead.
 */

import { toDownloadedMedia, type RawMediaLike } from "../media/audio-handler.js";
import type { NormalizedInboundMessage } from "../provider/WhatsAppProvider.js";

const PROVIDER_NAME = "webjs";

/** Minimal shape this module needs from a whatsapp-web.js Message --
 * kept narrow (rather than importing the library's own Message type)
 * so normalization logic is unit-testable without a real client. */
export interface RawMessageLike {
  id: { id: string };
  from: string;
  timestamp: number; // unix seconds, per whatsapp-web.js's own convention
  body: string;
  hasMedia: boolean;
  type: string;
}

export async function normalizeInboundMessage(
  raw: RawMessageLike,
  downloadMedia: () => Promise<RawMediaLike | null>
): Promise<NormalizedInboundMessage> {
  const timestampIso = new Date(raw.timestamp * 1000).toISOString();

  if (raw.hasMedia && (raw.type === "ptt" || raw.type === "audio")) {
    const rawMedia = await downloadMedia();
    if (rawMedia) {
      const media = toDownloadedMedia(rawMedia);
      return {
        provider: PROVIDER_NAME,
        messageId: raw.id.id,
        phoneNumber: raw.from,
        timestamp: timestampIso,
        type: "audio",
        text: "",
        media,
      };
    }
  }

  return {
    provider: PROVIDER_NAME,
    messageId: raw.id.id,
    phoneNumber: raw.from,
    timestamp: timestampIso,
    type: "text",
    text: raw.body ?? "",
  };
}
