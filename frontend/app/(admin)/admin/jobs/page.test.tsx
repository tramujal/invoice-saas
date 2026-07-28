import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PaginatedPlatformBackgroundJobsResponse, PlatformBackgroundJobEntry } from "@/lib/types";
import { renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import PlatformJobsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/jobs",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeJob(overrides: Partial<PlatformBackgroundJobEntry> = {}): PlatformBackgroundJobEntry {
  return {
    id: "job-1",
    organization_id: "org-1",
    job_type: "webhook.deliver",
    status: "pending",
    queue: "default",
    priority: 0,
    attempts: 0,
    max_attempts: 5,
    available_at: "2026-01-01T00:00:00Z",
    claimed_at: null,
    claimed_by: null,
    lease_expires_at: null,
    started_at: null,
    completed_at: null,
    failed_at: null,
    last_error_code: null,
    last_error_message: null,
    result_summary: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const oneJob: PaginatedPlatformBackgroundJobsResponse = { total: 1, items: [makeJob()] };

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe("PlatformJobsPage", () => {
  it("shows a loading state, then renders rows with human-readable job type and status", async () => {
    apiFetchMock.mockResolvedValue(oneJob);
    renderWithProviders(<PlatformJobsPage />);

    expect(screen.getByText("Loading background jobs…")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const table = screen.getByRole("table");
    const row = within(table).getByText("Webhook delivery").closest("tr")!;
    expect(within(row).getByText("Pending")).toBeInTheDocument();
    expect(within(row).getByText("org-1")).toBeInTheDocument();
  });

  it("shows the empty state when there are no jobs and no filters applied", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByText("No background jobs yet")).toBeInTheDocument());
  });

  it("shows a filtered-empty state with a reset action when filters are active but nothing matches", async () => {
    apiFetchMock.mockResolvedValue({ total: 0, items: [] });
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByText("No background jobs yet")).toBeInTheDocument());

    await user.type(screen.getByRole("searchbox", { name: "Search by organization ID" }), "org-9");
    await waitFor(() => expect(screen.getByText("No matching jobs")).toBeInTheDocument());

    const resetButtons = screen.getAllByRole("button", { name: "Reset filters" });
    await user.click(resetButtons[0]);
    await waitFor(() => expect(screen.getByText("No background jobs yet")).toBeInTheDocument());
  });

  it("shows a controlled error banner when the request fails", async () => {
    const { ApiError } = await import("@/lib/api");
    apiFetchMock.mockRejectedValue(new ApiError("boom", 500));
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
  });

  it("filters by status and shows an active filter chip that can be removed", async () => {
    apiFetchMock.mockResolvedValue(oneJob);
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByText("Webhook delivery")).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "pending");

    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).toContain("status=pending"));
    expect(screen.getByText("Status: Pending")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove filter: Status: Pending" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).not.toContain("status="));
  });

  it("paginates using limit/offset and disables Previous on the first page", async () => {
    apiFetchMock.mockResolvedValue({ total: 45, items: oneJob.items });
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByText("Webhook delivery")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(apiFetchMock.mock.calls.at(-1)?.[0]).toContain("offset=20"));
  });

  it("opens a read-only details drawer showing payload and timing fields", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === "/admin/jobs/job-1") {
        return Promise.resolve({ ...oneJob.items[0], payload: { delivery_id: "del-1" }, idempotency_key: "key-1" });
      }
      return Promise.resolve(oneJob);
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "More actions" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "View details" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Background job")).toBeInTheDocument();
    expect(within(dialog).getByText("delivery_id")).toBeInTheDocument();
    expect(within(dialog).getByText("del-1")).toBeInTheDocument();
  });

  it("disables Retry for a pending job and disables Cancel for a permanently-failed job", async () => {
    apiFetchMock.mockResolvedValue(oneJob);
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "More actions" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));

    expect(screen.getByRole("menuitem", { name: "Retry" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("menuitem", { name: "Cancel" })).not.toHaveAttribute("aria-disabled");
  });

  it("retries a permanently-failed job after entering a reason", async () => {
    const failedJob = makeJob({ status: "permanently_failed" });
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path === "/admin/jobs/job-1/retry" && method === "POST") {
        return Promise.resolve({ ...failedJob, id: "job-2" });
      }
      return Promise.resolve({ total: 1, items: [failedJob] });
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "More actions" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Retry" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Retry job" })).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Reason"), "Endpoint back online");
    await user.click(within(dialog).getByRole("button", { name: "Retry job" }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        "/admin/jobs/job-1/retry",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ reason: "Endpoint back online" }),
        })
      )
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("cancels a pending job after entering a reason", async () => {
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path === "/admin/jobs/job-1/cancel" && method === "POST") {
        return Promise.resolve(makeJob({ status: "cancelled" }));
      }
      return Promise.resolve(oneJob);
    });
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "More actions" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Cancel job" })).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Reason"), "Duplicate event");
    await user.click(within(dialog).getByRole("button", { name: "Cancel job" }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        "/admin/jobs/job-1/cancel",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ reason: "Duplicate event" }),
        })
      )
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the confirm button disabled until a reason is entered", async () => {
    apiFetchMock.mockResolvedValue(oneJob);
    const user = userEvent.setup();
    renderWithProviders(<PlatformJobsPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "More actions" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Cancel job" })).toBeDisabled();
  });
});
