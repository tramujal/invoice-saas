import { describe, expect, it } from "vitest";

import { NullWhatsAppProvider } from "../src/provider/NullWhatsAppProvider.js";
import { WhatsAppNotConfiguredError } from "../src/provider/WhatsAppProvider.js";

describe("NullWhatsAppProvider", () => {
  it("reports disconnected without throwing", async () => {
    const provider = new NullWhatsAppProvider();
    const status = await provider.getConnectionStatus();
    expect(status.state).toBe("disconnected");
    expect(status.connectedPhoneNumber).toBeNull();
  });

  it("rejects every mutating call with WhatsAppNotConfiguredError", async () => {
    const provider = new NullWhatsAppProvider();
    await expect(provider.requestQrCode()).rejects.toBeInstanceOf(WhatsAppNotConfiguredError);
    await expect(provider.sendTextMessage("+15551234567", "hi")).rejects.toBeInstanceOf(WhatsAppNotConfiguredError);
    await expect(provider.sendDocument("+15551234567", "a.pdf", Buffer.from("x"), "application/pdf")).rejects.toBeInstanceOf(
      WhatsAppNotConfiguredError
    );
    await expect(provider.reconnect()).rejects.toBeInstanceOf(WhatsAppNotConfiguredError);
    await expect(provider.disconnect()).rejects.toBeInstanceOf(WhatsAppNotConfiguredError);
    await expect(provider.deleteSession()).rejects.toBeInstanceOf(WhatsAppNotConfiguredError);
  });

  it("never invokes an inbound handler (nothing to receive)", () => {
    const provider = new NullWhatsAppProvider();
    let called = false;
    provider.onInboundMessage(() => {
      called = true;
    });
    expect(called).toBe(false);
  });
});
