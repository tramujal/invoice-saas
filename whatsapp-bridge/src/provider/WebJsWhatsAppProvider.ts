/**
 * The real WhatsAppProvider implementation, backed by whatsapp-web.js
 * (an UNOFFICIAL WhatsApp Web client automation library -- see
 * docs/whatsapp.md's "Unofficial WhatsApp risks" section in the main
 * repo. This class is the ONLY module in this bridge that imports
 * whatsapp-web.js directly; everything else in src/ depends only on the
 * WhatsAppProvider interface.
 *
 * Bounded reconnect backoff (never an infinite loop), explicit
 * connected/disconnected/qr_required/session_expired states, and a
 * graceful shutdown path are all implemented here per Phase 23 section
 * 19 ("Bridge reliability").
 */

// whatsapp-web.js is a plain CommonJS package (`module.exports = { Client:
// ..., ...Constants }`) whose only named export Node's CJS->ESM interop
// reliably detects is `Client` -- `LocalAuth`/`MessageMedia` silently
// resolve to `undefined` via a named import at runtime (this surfaced
// only when actually running the compiled bridge, not from `tsc` --
// TypeScript resolves both forms identically against the package's own
// .d.ts). Importing the default export and destructuring from it works
// for all of them, uniformly.
import whatsappWebJs from "whatsapp-web.js";
// `import type` is resolved purely from the package's .d.ts at compile
// time -- unaffected by the CJS->ESM runtime interop issue above, so
// `Client` is safe to use as a type here even though it's destructured
// off the default export (not imported by name) for its runtime value.
import type { Client as WhatsAppClient, Message } from "whatsapp-web.js";
import QRCode from "qrcode";

const { Client, LocalAuth, MessageMedia } = whatsappWebJs;

import { normalizeInboundMessage, type RawMessageLike } from "../transport/inbound-handler.js";
import { resolveSessionPath } from "../session/session-manager.js";
import type {
  NormalizedInboundMessage,
  WhatsAppConnectionState,
  WhatsAppConnectionStatus,
  WhatsAppProvider,
  WhatsAppQrCode,
} from "./WhatsAppProvider.js";
import { WhatsAppProviderError } from "./WhatsAppProvider.js";

export interface WebJsProviderConfig {
  reconnectInitialDelaySeconds: number;
  reconnectMaxDelaySeconds: number;
  reconnectMaxAttempts: number;
}

const QR_TTL_SECONDS = 60; // whatsapp-web.js itself rotates the QR roughly this often

export class WebJsWhatsAppProvider implements WhatsAppProvider {
  private client: WhatsAppClient;
  private state: WhatsAppConnectionState = "disconnected";
  private connectedPhoneNumber: string | null = null;
  private lastHeartbeatAt: string | null = null;
  private lastQr: WhatsAppQrCode | null = null;
  private inboundHandlers: Array<(message: NormalizedInboundMessage) => void> = [];
  private reconnectAttempts = 0;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private readonly config: WebJsProviderConfig;

  constructor(config: WebJsProviderConfig) {
    this.config = config;
    this.client = this.buildClient();
  }

  private buildClient(): WhatsAppClient {
    const client = new Client({
      authStrategy: new LocalAuth({ dataPath: resolveSessionPath() }),
      puppeteer: {
        headless: true,
        args: ["--no-sandbox", "--disable-setuid-sandbox"],
      },
    });

    client.on("qr", (qr: string) => {
      this.state = "qr_required";
      void this.updateQrCode(qr);
    });

    client.on("authenticated", () => {
      this.state = "connecting";
    });

    client.on("ready", () => {
      this.state = "connected";
      this.reconnectAttempts = 0;
      this.lastHeartbeatAt = new Date().toISOString();
      this.connectedPhoneNumber = client.info?.wid?.user ? `+${client.info.wid.user}` : null;
    });

    client.on("disconnected", (_reason: string) => {
      this.state = "session_expired";
      this.connectedPhoneNumber = null;
      this.scheduleReconnect();
    });

    client.on("auth_failure", () => {
      this.state = "session_expired";
      this.connectedPhoneNumber = null;
    });

    client.on("message", (message: Message) => {
      void this.handleIncomingMessage(message);
    });

    return client;
  }

  private async updateQrCode(rawQr: string): Promise<void> {
    const dataUrl = await QRCode.toDataURL(rawQr);
    const base64 = dataUrl.split(",")[1] ?? "";
    this.lastQr = {
      qrDataBase64: base64,
      expiresAt: new Date(Date.now() + QR_TTL_SECONDS * 1000).toISOString(),
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    if (this.reconnectAttempts >= this.config.reconnectMaxAttempts) {
      // Bounded -- never an infinite reconnect loop (Phase 23 section
      // 19's explicit requirement). Stays in session_expired; an
      // operator must explicitly call reconnect()/request a new QR from
      // Settings -> WhatsApp.
      return;
    }
    const delaySeconds = Math.min(
      this.config.reconnectInitialDelaySeconds * 2 ** this.reconnectAttempts,
      this.config.reconnectMaxDelaySeconds
    );
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.client.initialize().catch(() => this.scheduleReconnect());
    }, delaySeconds * 1000);
  }

  private async handleIncomingMessage(message: Message): Promise<void> {
    const raw: RawMessageLike = {
      id: { id: message.id.id },
      from: message.from,
      timestamp: message.timestamp,
      body: message.body,
      hasMedia: message.hasMedia,
      type: message.type,
    };
    const normalized = await normalizeInboundMessage(raw, async () => {
      if (!message.hasMedia) return null;
      try {
        const media = await message.downloadMedia();
        return media ? { mimetype: media.mimetype, data: media.data } : null;
      } catch {
        return null;
      }
    });
    for (const handler of this.inboundHandlers) {
      handler(normalized);
    }
  }

  async initialize(): Promise<void> {
    this.state = "connecting";
    await this.client.initialize();
  }

  async getConnectionStatus(): Promise<WhatsAppConnectionStatus> {
    return {
      state: this.state,
      connectedPhoneNumber: this.connectedPhoneNumber,
      lastHeartbeatAt: this.lastHeartbeatAt,
    };
  }

  async requestQrCode(): Promise<WhatsAppQrCode> {
    if (!this.lastQr) {
      throw new WhatsAppProviderError("No QR code is currently available. Try again shortly.");
    }
    return this.lastQr;
  }

  async sendTextMessage(phoneNumber: string, text: string): Promise<void> {
    await this.client.sendMessage(toChatId(phoneNumber), text);
  }

  async sendDocument(phoneNumber: string, filename: string, content: Buffer, mimeType: string): Promise<void> {
    const media = new MessageMedia(mimeType, content.toString("base64"), filename);
    await this.client.sendMessage(toChatId(phoneNumber), media);
  }

  async reconnect(): Promise<void> {
    this.reconnectAttempts = 0;
    try {
      await this.client.destroy();
    } catch {
      // Already torn down / never fully initialized -- proceed to a
      // fresh client regardless.
    }
    this.client = this.buildClient();
    await this.initialize();
  }

  async disconnect(): Promise<void> {
    this.state = "disconnected";
    this.connectedPhoneNumber = null;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    await this.client.logout();
  }

  async deleteSession(): Promise<void> {
    await this.disconnect();
    const { deleteSession } = await import("../session/session-manager.js");
    await deleteSession();
  }

  onInboundMessage(handler: (message: NormalizedInboundMessage) => void): void {
    this.inboundHandlers.push(handler);
  }

  /** Graceful shutdown -- Phase 23 section 19. Called from index.ts's
   * SIGTERM/SIGINT handler. */
  async shutdown(): Promise<void> {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    try {
      await this.client.destroy();
    } catch {
      // Best-effort -- the process is exiting regardless.
    }
  }
}

function toChatId(phoneNumber: string): string {
  // whatsapp-web.js chat ids are "<digits>@c.us" -- strip the leading
  // '+' this bridge's own normalized phone numbers always carry.
  const digits = phoneNumber.replace(/[^\d]/g, "");
  return `${digits}@c.us`;
}
