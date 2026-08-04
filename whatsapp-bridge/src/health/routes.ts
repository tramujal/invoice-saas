/**
 * Unauthenticated health/readiness endpoints (Phase 23 section 19) --
 * deliberately NOT behind the HMAC signature check (a container
 * orchestrator's health probe has no way to sign a request), and
 * deliberately reveal nothing about WhatsApp connection state or any
 * secret -- that's what the signed GET /status route
 * (src/transport/outbound-handler.ts) is for.
 */

import type { Request, Response, Router as RouterType } from "express";
import { Router } from "express";

import type { WhatsAppProvider } from "../provider/WhatsAppProvider.js";

export function buildHealthRouter(provider: WhatsAppProvider): RouterType {
  const router = Router();

  // Liveness -- "is this process up at all." Always 200 once the HTTP
  // server itself is accepting connections.
  router.get("/health", (_req: Request, res: Response) => {
    res.status(200).json({ status: "ok" });
  });

  // Readiness -- "can this process currently do useful work." Reflects
  // only whether the provider object itself is alive and answering, not
  // whether WhatsApp is actually connected (a disconnected/qr_required
  // bridge is still a perfectly "ready" process -- see GET /status for
  // the actual connection state).
  router.get("/ready", async (_req: Request, res: Response) => {
    try {
      await provider.getConnectionStatus();
      res.status(200).json({ status: "ready" });
    } catch {
      res.status(503).json({ status: "not_ready" });
    }
  });

  return router;
}
