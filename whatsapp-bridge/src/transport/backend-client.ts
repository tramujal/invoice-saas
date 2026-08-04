/**
 * The bridge's outbound HTTP client to the FastAPI backend -- posts every
 * normalized inbound WhatsApp message to
 * POST {BACKEND_BASE_URL}/whatsapp/bridge/inbound, signed the same way
 * the backend signs requests back to this bridge (see
 * src/security/request-signing.ts).
 *
 * This is the ONLY place this bridge talks to the backend's database-
 * backed API -- and even here, it never reads or writes anything beyond
 * POSTing the envelope; every business decision happens on the FastAPI
 * side (see app/whatsapp/service.py).
 */

import { signBridgeRequest, SIGNATURE_HEADER } from "../security/request-signing.js";
import type { NormalizedInboundMessage } from "../provider/WhatsAppProvider.js";

export interface BackendClientConfig {
  backendBaseUrl: string;
  bridgeSecret: string;
  requestTimeoutSeconds: number;
}

export class BackendRequestError extends Error {}

export async function postInboundMessage(
  config: BackendClientConfig,
  message: NormalizedInboundMessage
): Promise<void> {
  const body = Buffer.from(
    JSON.stringify({
      provider: message.provider,
      message_id: message.messageId,
      phone_number: message.phoneNumber,
      timestamp: message.timestamp,
      type: message.type,
      text: message.text,
      media: message.media
        ? {
            mime_type: message.media.mimeType,
            size_bytes: message.media.sizeBytes,
            content_base64: message.media.contentBase64,
          }
        : undefined,
    }),
    "utf-8"
  );

  const timestampSeconds = Math.floor(Date.now() / 1000);
  const signature = signBridgeRequest(config.bridgeSecret, timestampSeconds, body);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.requestTimeoutSeconds * 1000);

  try {
    const response = await fetch(`${config.backendBaseUrl.replace(/\/$/, "")}/whatsapp/bridge/inbound`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SIGNATURE_HEADER]: signature,
      },
      body,
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new BackendRequestError(`Backend rejected inbound message (status ${response.status}).`);
    }
  } catch (error) {
    if (error instanceof BackendRequestError) throw error;
    // Never includes the bridge secret; the fetch error's own message may
    // include the target URL, so it's deliberately not logged/rethrown
    // verbatim past this point either.
    throw new BackendRequestError("Failed to reach the backend.");
  } finally {
    clearTimeout(timeout);
  }
}
