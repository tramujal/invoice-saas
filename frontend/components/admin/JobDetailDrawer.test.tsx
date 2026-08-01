import { describe, expect, it, vi } from "vitest";

import { renderWithProviders, screen } from "@/tests/test-utils";
import type { PlatformBackgroundJobDetail } from "@/lib/types";

import { JobDetailDrawer } from "./JobDetailDrawer";

/** Phase UX1 regression coverage -- claimed_by (a worker id) and payload
 * values can be arbitrary-length, unbroken strings with no natural wrap
 * point. */
const job: PlatformBackgroundJobDetail = {
  id: "job-1",
  organization_id: "org-1",
  job_type: "webhook.deliver",
  status: "succeeded",
  queue: "default",
  priority: 0,
  attempts: 1,
  max_attempts: 5,
  available_at: "2026-01-15T10:00:00Z",
  claimed_at: "2026-01-15T10:00:01Z",
  claimed_by: "a-very-long-unbroken-worker-hostname-identifier-with-no-spaces-1234567890",
  lease_expires_at: null,
  started_at: "2026-01-15T10:00:01Z",
  completed_at: "2026-01-15T10:00:02Z",
  failed_at: null,
  last_error_code: null,
  last_error_message: null,
  result_summary: null,
  created_at: "2026-01-15T10:00:00Z",
  updated_at: "2026-01-15T10:00:02Z",
  payload: { url: "https://example.com/a/very/long/unbroken/webhook/callback/path/1234567890" },
  idempotency_key: null,
};

describe("JobDetailDrawer", () => {
  it("uses a viewport-safe width instead of a bare w-full", () => {
    renderWithProviders(<JobDetailDrawer job={job} onClose={vi.fn()} formatTimestamp={(v) => v ?? "—"} />);

    const dialog = screen.getByRole("dialog", { name: "Background job" });
    expect(dialog).toHaveClass("w-[calc(100vw-2rem)]");
  });

  it("shrinks the claimed-by value column so a long worker id can't force the row wider", () => {
    renderWithProviders(<JobDetailDrawer job={job} onClose={vi.fn()} formatTimestamp={(v) => v ?? "—"} />);

    const value = screen.getByText(job.claimed_by!);
    expect(value).toHaveClass("min-w-0");
    expect(value).toHaveClass("flex-1");
    expect(value).toHaveClass("break-all");
  });

  it("shrinks payload value columns so a long URL can't force the row wider", () => {
    renderWithProviders(<JobDetailDrawer job={job} onClose={vi.fn()} formatTimestamp={(v) => v ?? "—"} />);

    const value = screen.getByText(job.payload.url as string);
    expect(value).toHaveClass("min-w-0");
    expect(value).toHaveClass("flex-1");
    expect(value).toHaveClass("break-all");

    const key = screen.getByText("url");
    expect(key).toHaveClass("shrink-0");
  });
});
