import { describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";
import type { PlatformAuditLogEntry } from "@/lib/types";

import { AuditLogEntryDrawer } from "./AuditLogEntryDrawer";

/** Phase UX1 regression coverage: this is the platform-admin twin of
 * AuditEntryDetailsDrawer.tsx (Settings), which shares the exact same
 * overflow risk -- arbitrary-length actor emails, target names, and
 * JSON-stringified detail values with no natural wrap point that could
 * otherwise force this dialog (and the page behind it) wider than the
 * viewport on mobile. */
const entry: PlatformAuditLogEntry = {
  id: "entry-1",
  action: "user.disabled",
  actor_user_id: "actor-1",
  actor_email: "a-very-long-unbroken-administrator-email-address@example-corp.com",
  target_type: "user",
  target_organization_id: null,
  target_organization_name: null,
  target_user_id: "user-1",
  target_user_email: "target@example.com",
  reason: "policy violation",
  details: { requestId: "req_aVeryLongUnbrokenIdentifierWithNoSpacesOrHyphensAtAll1234567890" },
  client_ip: "203.0.113.0",
  created_at: "2026-01-15T10:30:00Z",
};

describe("AuditLogEntryDrawer", () => {
  it("uses a viewport-safe width instead of a bare w-full", () => {
    renderWithProviders(
      <AuditLogEntryDrawer
        entry={entry}
        onClose={vi.fn()}
        actionLabel={(code) => code}
        formatTimestamp={(value) => value}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Audit log entry" });
    expect(dialog).toHaveClass("w-[calc(100vw-2rem)]");
  });

  it("lets the actor email wrap instead of overflowing its container", () => {
    renderWithProviders(
      <AuditLogEntryDrawer
        entry={entry}
        onClose={vi.fn()}
        actionLabel={(code) => code}
        formatTimestamp={(value) => value}
      />
    );

    const actorValue = screen.getByText(entry.actor_email);
    expect(actorValue).toHaveClass("break-words");
  });

  it("shrinks the detail-value column instead of letting long JSON values force the row wider", () => {
    renderWithProviders(
      <AuditLogEntryDrawer
        entry={entry}
        onClose={vi.fn()}
        actionLabel={(code) => code}
        formatTimestamp={(value) => value}
      />
    );

    const value = screen.getByText("req_aVeryLongUnbrokenIdentifierWithNoSpacesOrHyphensAtAll1234567890");
    expect(value).toHaveClass("min-w-0");
    expect(value).toHaveClass("flex-1");
    expect(value).toHaveClass("break-words");

    const key = screen.getByText("requestId");
    expect(key).toHaveClass("shrink-0");
  });
});
