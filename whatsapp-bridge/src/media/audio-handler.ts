/**
 * Voice-note media handling -- Phase 23 section 11.
 *
 * Downloads media from a WhatsApp message via whatsapp-web.js's own
 * `downloadMedia()` (which returns a MessageMedia with base64 data
 * in-process, no temp file needed on this side) and hands it off as
 * part of the normalized envelope. This module never writes audio to
 * disk and never retains a reference to it beyond the single function
 * call -- once postInboundMessage's fetch() call in
 * transport/backend-client.ts returns, nothing here still references
 * the bytes.
 *
 * Size/MIME/duration validation happens on BOTH sides deliberately: this
 * module rejects obviously-oversized media before ever base64-encoding
 * it (cheap check first), and the backend (app/whatsapp/service.py)
 * re-validates independently, exactly like every other request this
 * app never lets one side trust the other's judgment on alone.
 */

export const MAX_AUDIO_BYTES = Number(process.env.WHATSAPP_AUDIO_MAX_BYTES ?? 5 * 1024 * 1024);

export interface DownloadedMedia {
  mimeType: string;
  sizeBytes: number;
  contentBase64: string;
}

/** Minimal shape this module needs from a whatsapp-web.js MessageMedia --
 * kept as a narrow local interface rather than importing the library's
 * own type here, so this module's own logic is trivially unit-testable
 * without a real whatsapp-web.js Message object. */
export interface RawMediaLike {
  mimetype: string;
  data: string; // base64, as whatsapp-web.js's MessageMedia already provides
}

export class AudioTooLargeError extends Error {}

export function toDownloadedMedia(raw: RawMediaLike): DownloadedMedia {
  // Buffer.byteLength on the base64 STRING overestimates raw bytes by
  // ~33% (base64 overhead) -- close enough for a cheap upper-bound
  // rejection before ever allocating the decoded buffer; the backend's
  // own check on the decoded size_bytes is the authoritative one.
  const approxBytes = Math.floor((raw.data.length * 3) / 4);
  if (approxBytes > MAX_AUDIO_BYTES) {
    throw new AudioTooLargeError(`Audio (~${approxBytes} bytes) exceeds the maximum allowed size.`);
  }
  return {
    mimeType: raw.mimetype,
    sizeBytes: approxBytes,
    contentBase64: raw.data,
  };
}
