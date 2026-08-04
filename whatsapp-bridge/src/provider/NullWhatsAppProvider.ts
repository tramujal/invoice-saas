/**
 * Safe default provider -- used when this bridge process starts without
 * a real WhatsApp connection configured, mirroring the Python backend's
 * app/whatsapp/null_provider.py. Every mutating method rejects; status
 * reports "disconnected" rather than throwing, so the health/status
 * routes always return something sane.
 */

import type {
  NormalizedInboundMessage,
  WhatsAppConnectionStatus,
  WhatsAppProvider,
  WhatsAppQrCode,
} from "./WhatsAppProvider.js";
import { WhatsAppNotConfiguredError } from "./WhatsAppProvider.js";

export class NullWhatsAppProvider implements WhatsAppProvider {
  async getConnectionStatus(): Promise<WhatsAppConnectionStatus> {
    return { state: "disconnected", connectedPhoneNumber: null, lastHeartbeatAt: null };
  }

  async requestQrCode(): Promise<WhatsAppQrCode> {
    throw new WhatsAppNotConfiguredError("WhatsApp Web client is not initialized.");
  }

  async sendTextMessage(): Promise<void> {
    throw new WhatsAppNotConfiguredError("WhatsApp Web client is not initialized.");
  }

  async sendDocument(): Promise<void> {
    throw new WhatsAppNotConfiguredError("WhatsApp Web client is not initialized.");
  }

  async reconnect(): Promise<void> {
    throw new WhatsAppNotConfiguredError("WhatsApp Web client is not initialized.");
  }

  async disconnect(): Promise<void> {
    throw new WhatsAppNotConfiguredError("WhatsApp Web client is not initialized.");
  }

  async deleteSession(): Promise<void> {
    throw new WhatsAppNotConfiguredError("WhatsApp Web client is not initialized.");
  }

  onInboundMessage(_handler: (message: NormalizedInboundMessage) => void): void {
    // No-op -- nothing ever calls back since no client is connected.
  }
}
