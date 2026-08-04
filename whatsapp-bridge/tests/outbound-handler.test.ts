import express from "express";
import type { Request } from "express";
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";

import { buildHealthRouter } from "../src/health/routes.js";
import { buildOutboundRouter } from "../src/transport/outbound-handler.js";
import { signBridgeRequest, SIGNATURE_HEADER } from "../src/security/request-signing.js";
import { FakeWhatsAppProvider } from "./fake-provider.js";

const SECRET = "test-secret";

function buildApp(provider: FakeWhatsAppProvider) {
  const app = express();
  app.use(
    express.json({
      verify: (req: Request & { rawBody?: Buffer }, _res, buf) => {
        req.rawBody = Buffer.from(buf);
      },
    })
  );
  app.use("/", buildHealthRouter(provider));
  app.use("/", buildOutboundRouter(provider, { bridgeSecret: SECRET, signatureToleranceSeconds: 300 }));
  return app;
}

function signedHeaders(body: unknown): Record<string, string> {
  const raw = Buffer.from(JSON.stringify(body ?? {}));
  const ts = Math.floor(Date.now() / 1000);
  return { [SIGNATURE_HEADER]: signBridgeRequest(SECRET, ts, raw) };
}

describe("health routes", () => {
  it("GET /health is unauthenticated and always ok", async () => {
    const app = buildApp(new FakeWhatsAppProvider());
    const response = await request(app).get("/health");
    expect(response.status).toBe(200);
    expect(response.body.status).toBe("ok");
  });

  it("GET /ready reflects provider liveness", async () => {
    const app = buildApp(new FakeWhatsAppProvider());
    const response = await request(app).get("/ready");
    expect(response.status).toBe(200);
  });
});

describe("outbound-handler signature enforcement", () => {
  let provider: FakeWhatsAppProvider;
  let app: express.Express;

  beforeEach(() => {
    provider = new FakeWhatsAppProvider();
    app = buildApp(provider);
  });

  it("rejects a request with no signature header", async () => {
    const response = await request(app).get("/status");
    expect(response.status).toBe(401);
  });

  it("rejects a request with a wrong signature", async () => {
    const response = await request(app).get("/status").set(SIGNATURE_HEADER, "t=1,v1=deadbeef");
    expect(response.status).toBe(401);
  });

  it("accepts a correctly signed GET /status", async () => {
    // The real backend client (app/whatsapp/bridge_provider.py) always
    // sends a literal "{}" body, even for GET requests -- never an empty
    // buffer -- so the signature here must cover "{}" too.
    const ts = Math.floor(Date.now() / 1000);
    const header = signBridgeRequest(SECRET, ts, Buffer.from("{}"));
    const response = await request(app)
      .get("/status")
      .set("Content-Type", "application/json")
      .set(SIGNATURE_HEADER, header)
      .send({});
    expect(response.status).toBe(200);
    expect(response.body.state).toBe("connected");
  });

  it("POST /send/text delivers to the provider when correctly signed", async () => {
    const body = { phone_number: "+15551234567", text: "hola" };
    const response = await request(app).post("/send/text").set(signedHeaders(body)).send(body);
    expect(response.status).toBe(200);
    expect(provider.sentText).toEqual([{ phoneNumber: "+15551234567", text: "hola" }]);
  });

  it("POST /send/document delivers to the provider when correctly signed", async () => {
    const body = {
      phone_number: "+15551234567",
      filename: "INV-000001.pdf",
      content_base64: Buffer.from("pdf-bytes").toString("base64"),
      mime_type: "application/pdf",
    };
    const response = await request(app).post("/send/document").set(signedHeaders(body)).send(body);
    expect(response.status).toBe(200);
    expect(provider.sentDocuments).toHaveLength(1);
    expect(provider.sentDocuments[0].filename).toBe("INV-000001.pdf");
  });

  it("POST /reconnect, /disconnect, /session/delete each reach the provider exactly once", async () => {
    for (const path of ["/reconnect", "/disconnect", "/session/delete"]) {
      const response = await request(app).post(path).set(signedHeaders({})).send({});
      expect(response.status).toBe(200);
    }
    expect(provider.reconnectCalls).toBe(1);
    expect(provider.disconnectCalls).toBe(1);
    expect(provider.deleteSessionCalls).toBe(1);
  });

  it("rejects /send/text with a signed but malformed body", async () => {
    const body = { phone_number: "+15551234567" }; // missing `text`
    const response = await request(app).post("/send/text").set(signedHeaders(body)).send(body);
    expect(response.status).toBe(400);
  });
});
