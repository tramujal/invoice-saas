/**
 * Provider-agnostic WhatsApp transport interface -- mirrors the Python
 * backend's app/whatsapp/provider_base.py exactly, so the two sides of
 * this bridge agree on one vocabulary. Every HTTP route in
 * src/transport/outbound-handler.ts talks ONLY to this interface, never
 * to a concrete provider (WebJsWhatsAppProvider today; a future Meta
 * Cloud API adapter would implement this same interface -- see
 * docs/whatsapp.md's migration-path section in the main repo).
 */

export type WhatsAppConnectionState =
  | "disconnected"
  | "qr_required"
  | "connecting"
  | "connected"
  | "session_expired";

export interface WhatsAppConnectionStatus {
  state: WhatsAppConnectionState;
  connectedPhoneNumber: string | null;
  lastHeartbeatAt: string | null;
}

export interface WhatsAppQrCode {
  qrDataBase64: string;
  expiresAt: string;
}

export class WhatsAppProviderError extends Error {}
export class WhatsAppNotConfiguredError extends WhatsAppProviderError {}

/** One normalized inbound message, handed to the backend-client -- see
 * docs/whatsapp.md's "Normalized inbound envelope" shape (kept in sync
 * with app/whatsapp/schemas.py::WhatsAppInboundEnvelope on the Python
 * side). */
export interface NormalizedInboundMessage {
  provider: string;
  messageId: string;
  phoneNumber: string;
  timestamp: string;
  type: "text" | "audio";
  text: string;
  media?: {
    mimeType: string;
    sizeBytes: number;
    contentBase64: string;
  };
}

export interface WhatsAppProvider {
  getConnectionStatus(): Promise<WhatsAppConnectionStatus>;
  requestQrCode(): Promise<WhatsAppQrCode>;
  sendTextMessage(phoneNumber: string, text: string): Promise<void>;
  sendDocument(phoneNumber: string, filename: string, content: Buffer, mimeType: string): Promise<void>;
  reconnect(): Promise<void>;
  disconnect(): Promise<void>;
  deleteSession(): Promise<void>;
  /** Registers a callback invoked for every normalized inbound message
   * this provider receives -- src/index.ts wires this to
   * transport/backend-client.ts's postInboundMessage. */
  onInboundMessage(handler: (message: NormalizedInboundMessage) => void): void;
}
