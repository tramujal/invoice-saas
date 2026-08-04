/**
 * The bridge's inbound HTTP surface (confusingly named relative to the
 * WHOLE system's data flow, but "outbound" from this bridge's own
 * perspective: these are the instructions the BACKEND sends TO this
 * bridge -- "send this text," "give me a QR," "reconnect" -- see Phase
 * 23 section 1's own architecture list ("receive reply instructions;
 * send text/PDF replies through WhatsApp")).
 *
 * Every route requires a valid HMAC signature (src/security/request-
 * signing.ts) -- there is no other authentication on this bridge at all,
 * so an unsigned or wrongly-signed request is rejected uniformly, with a
 * sanitized error that never distinguishes which specific check failed.
 */

import type { Request, Response, Router as RouterType } from "express";
import { Router } from "express";

import { InvalidBridgeSignatureError, SIGNATURE_HEADER, verifyBridgeSignature } from "../security/request-signing.js";
import type { WhatsAppProvider } from "../provider/WhatsAppProvider.js";
import { WhatsAppProviderError } from "../provider/WhatsAppProvider.js";

export interface OutboundHandlerConfig {
  bridgeSecret: string;
  signatureToleranceSeconds: number;
}

function verifySignedRequest(req: Request, config: OutboundHandlerConfig): Buffer {
  const body = (req as Request & { rawBody?: Buffer }).rawBody ?? Buffer.from(JSON.stringify(req.body ?? {}));
  verifyBridgeSignature({
    secret: config.bridgeSecret,
    signatureHeader: req.header(SIGNATURE_HEADER),
    body,
    toleranceSeconds: config.signatureToleranceSeconds,
  });
  return body;
}

export function buildOutboundRouter(provider: WhatsAppProvider, config: OutboundHandlerConfig): RouterType {
  const router = Router();

  router.use((req: Request, res: Response, next) => {
    try {
      verifySignedRequest(req, config);
      next();
    } catch (error) {
      if (error instanceof InvalidBridgeSignatureError) {
        res.status(401).json({ code: "invalid_signature", message: "Invalid or missing bridge signature." });
        return;
      }
      next(error);
    }
  });

  router.get("/status", async (_req: Request, res: Response) => {
    const status = await provider.getConnectionStatus();
    res.json({
      state: status.state,
      connected_phone_number: status.connectedPhoneNumber,
      last_heartbeat_at: status.lastHeartbeatAt,
    });
  });

  router.post("/qr", async (_req: Request, res: Response) => {
    try {
      const qr = await provider.requestQrCode();
      res.json({ qr_data_base64: qr.qrDataBase64, expires_at: qr.expiresAt });
    } catch (error) {
      respondProviderError(res, error);
    }
  });

  router.post("/send/text", async (req: Request, res: Response) => {
    const { phone_number: phoneNumber, text } = req.body ?? {};
    if (typeof phoneNumber !== "string" || typeof text !== "string") {
      res.status(400).json({ code: "invalid_request", message: "phone_number and text are required." });
      return;
    }
    try {
      await provider.sendTextMessage(phoneNumber, text);
      res.json({ status: "sent" });
    } catch (error) {
      respondProviderError(res, error);
    }
  });

  router.post("/send/document", async (req: Request, res: Response) => {
    const { phone_number: phoneNumber, filename, content_base64: contentBase64, mime_type: mimeType } = req.body ?? {};
    if (
      typeof phoneNumber !== "string" ||
      typeof filename !== "string" ||
      typeof contentBase64 !== "string" ||
      typeof mimeType !== "string"
    ) {
      res.status(400).json({ code: "invalid_request", message: "Missing required document fields." });
      return;
    }
    try {
      await provider.sendDocument(phoneNumber, filename, Buffer.from(contentBase64, "base64"), mimeType);
      res.json({ status: "sent" });
    } catch (error) {
      respondProviderError(res, error);
    }
  });

  router.post("/reconnect", async (_req: Request, res: Response) => {
    try {
      await provider.reconnect();
      res.json({ status: "reconnecting" });
    } catch (error) {
      respondProviderError(res, error);
    }
  });

  router.post("/disconnect", async (_req: Request, res: Response) => {
    try {
      await provider.disconnect();
      res.json({ status: "disconnected" });
    } catch (error) {
      respondProviderError(res, error);
    }
  });

  router.post("/session/delete", async (_req: Request, res: Response) => {
    try {
      await provider.deleteSession();
      res.json({ status: "session_deleted" });
    } catch (error) {
      respondProviderError(res, error);
    }
  });

  return router;
}

function respondProviderError(res: Response, error: unknown): void {
  if (error instanceof WhatsAppProviderError) {
    res.status(502).json({ code: "whatsapp_provider_error", message: "The WhatsApp client reported an error." });
    return;
  }
  res.status(500).json({ code: "internal_error", message: "An unexpected error occurred." });
}
