import type {
  NormalizedInboundMessage,
  WhatsAppConnectionStatus,
  WhatsAppProvider,
  WhatsAppQrCode,
} from "../src/provider/WhatsAppProvider.js";

/** A controllable WhatsAppProvider for exercising the outbound HTTP
 * routes without a real whatsapp-web.js client. */
export class FakeWhatsAppProvider implements WhatsAppProvider {
  sentText: Array<{ phoneNumber: string; text: string }> = [];
  sentDocuments: Array<{ phoneNumber: string; filename: string; mimeType: string }> = [];
  reconnectCalls = 0;
  disconnectCalls = 0;
  deleteSessionCalls = 0;

  async getConnectionStatus(): Promise<WhatsAppConnectionStatus> {
    return { state: "connected", connectedPhoneNumber: "+15550000000", lastHeartbeatAt: null };
  }

  async requestQrCode(): Promise<WhatsAppQrCode> {
    return { qrDataBase64: "ZmFrZQ==", expiresAt: "2026-01-01T00:00:00Z" };
  }

  async sendTextMessage(phoneNumber: string, text: string): Promise<void> {
    this.sentText.push({ phoneNumber, text });
  }

  async sendDocument(phoneNumber: string, filename: string, _content: Buffer, mimeType: string): Promise<void> {
    this.sentDocuments.push({ phoneNumber, filename, mimeType });
  }

  async reconnect(): Promise<void> {
    this.reconnectCalls += 1;
  }

  async disconnect(): Promise<void> {
    this.disconnectCalls += 1;
  }

  async deleteSession(): Promise<void> {
    this.deleteSessionCalls += 1;
  }

  onInboundMessage(_handler: (message: NormalizedInboundMessage) => void): void {
    // Not exercised by the outbound-route tests.
  }
}
