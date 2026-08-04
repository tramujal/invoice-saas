/**
 * Entry point -- wires together the WhatsApp provider, the signed
 * outbound-instruction HTTP surface, health/readiness routes, and
 * inbound-message forwarding to the backend. Transport-only: this file
 * (and everything it imports) never touches a database, never evaluates
 * RBAC, never interprets a command -- see docs/whatsapp.md's
 * architecture section in the main repo.
 */

import express from "express";
import type { Request } from "express";

import { postInboundMessage } from "./transport/backend-client.js";
import { buildOutboundRouter } from "./transport/outbound-handler.js";
import { buildHealthRouter } from "./health/routes.js";
import { NullWhatsAppProvider } from "./provider/NullWhatsAppProvider.js";
import { WebJsWhatsAppProvider } from "./provider/WebJsWhatsAppProvider.js";
import type { WhatsAppProvider } from "./provider/WhatsAppProvider.js";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    // Fails loudly and immediately at startup -- never silently runs
    // unsigned/unauthenticated, and never falls back to a default secret.
    // eslint-disable-next-line no-console
    console.error(`Missing required environment variable: ${name}`);
    process.exit(1);
  }
  return value;
}

async function main(): Promise<void> {
  const port = Number(process.env.PORT ?? 3100);
  const bridgeSecret = requireEnv("WHATSAPP_BRIDGE_SECRET");
  const backendBaseUrl = process.env.BACKEND_BASE_URL ?? "http://localhost:8000";
  const signatureToleranceSeconds = Number(process.env.SIGNATURE_TOLERANCE_SECONDS ?? 300);
  const backendRequestTimeoutSeconds = Number(process.env.BACKEND_REQUEST_TIMEOUT_SECONDS ?? 10);
  // "null" is a local-development/testing escape hatch to exercise the
  // HTTP surface without launching a real (Chromium-backed) WhatsApp Web
  // client -- never set in a real deployment.
  const providerKind = process.env.WHATSAPP_BRIDGE_PROVIDER ?? "webjs";

  const provider: WhatsAppProvider =
    providerKind === "null"
      ? new NullWhatsAppProvider()
      : new WebJsWhatsAppProvider({
          reconnectInitialDelaySeconds: Number(process.env.RECONNECT_INITIAL_DELAY_SECONDS ?? 5),
          reconnectMaxDelaySeconds: Number(process.env.RECONNECT_MAX_DELAY_SECONDS ?? 300),
          reconnectMaxAttempts: Number(process.env.RECONNECT_MAX_ATTEMPTS ?? 20),
        });

  provider.onInboundMessage((message) => {
    postInboundMessage(
      { backendBaseUrl, bridgeSecret, requestTimeoutSeconds: backendRequestTimeoutSeconds },
      message
    ).catch((error: unknown) => {
      // eslint-disable-next-line no-console
      console.error("Failed to forward inbound WhatsApp message to backend:", (error as Error).message);
    });
  });

  const app = express();
  app.use(
    express.json({
      limit: "16mb", // generous for a base64-encoded voice note + envelope
      verify: (req: Request & { rawBody?: Buffer }, _res, buf) => {
        req.rawBody = Buffer.from(buf);
      },
    })
  );

  app.use("/", buildHealthRouter(provider));
  app.use("/", buildOutboundRouter(provider, { bridgeSecret, signatureToleranceSeconds }));

  const server = app.listen(port, () => {
    // eslint-disable-next-line no-console
    console.log(`whatsapp-bridge listening on port ${port} (provider=${providerKind})`);
  });

  if (provider instanceof WebJsWhatsAppProvider) {
    provider.initialize().catch((error: unknown) => {
      // eslint-disable-next-line no-console
      console.error("Failed to initialize WhatsApp Web client:", (error as Error).message);
    });
  }

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    // eslint-disable-next-line no-console
    console.log(`Received ${signal}, shutting down gracefully...`);
    server.close();
    if (provider instanceof WebJsWhatsAppProvider) {
      await provider.shutdown();
    }
    process.exit(0);
  };

  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

void main();
