import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type {
  PaginatedWebhookDeliveries,
  WebhookEndpoint,
  WebhookEndpointCreated,
  WebhookEventCatalogEntry,
} from "@/lib/types";
import { renderWithProviders } from "@/tests/test-utils";

import WebhooksPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/webhooks",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const catalog: WebhookEventCatalogEntry[] = [
  { event_type: "customer.created", domain: "customer" },
  { event_type: "invoice.sent", domain: "invoice" },
];

const existingEndpoint: WebhookEndpoint = {
  id: "ep-1",
  organization_id: "org-1",
  url: "https://example.com/hook",
  description: "Order sync",
  subscribed_events: ["customer.created"],
  enabled: true,
  active: true,
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  last_rotated_at: null,
};

function mockDefault(endpoints: WebhookEndpoint[]) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (path.endsWith("/webhooks") && method === "GET") return Promise.resolve(endpoints);
    if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
    return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
  });
});

describe("WebhooksPage", () => {
  it("renders existing endpoints without ever showing a secret", async () => {
    mockDefault([existingEndpoint]);
    renderWithProviders(<WebhooksPage />);

    await waitFor(() => expect(screen.getByText("https://example.com/hook")).toBeInTheDocument());
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.queryByText(/whsec_/)).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no endpoints", async () => {
    mockDefault([]);
    renderWithProviders(<WebhooksPage />);

    await waitFor(() => expect(screen.getByText("No webhook endpoints yet")).toBeInTheDocument());
  });

  it("requires a valid url and at least one event before submitting", async () => {
    mockDefault([]);
    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Add endpoint" }));
    expect(await screen.findByText("Enter a valid https:// URL.")).toBeInTheDocument();
  });

  it("creates an endpoint and shows the one-time secret dialog", async () => {
    const created: WebhookEndpointCreated = { ...existingEndpoint, id: "ep-2", secret: "whsec_supersecretvalue" };
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/webhooks") && method === "GET") return Promise.resolve([]);
      if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
      if (path.endsWith("/webhooks") && method === "POST") return Promise.resolve(created);
      return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/Endpoint URL/), "https://example.com/new-hook");
    await user.click(screen.getByLabelText("Customer created"));
    await user.click(screen.getByRole("button", { name: "Add endpoint" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("whsec_supersecretvalue")).toBeInTheDocument();
  });

  it("shows the plan-limit dialog when the webhook quota is reached (409 plan_limit_reached)", async () => {
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/webhooks") && method === "GET") return Promise.resolve([existingEndpoint]);
      if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
      if (path.endsWith("/webhooks") && method === "POST") {
        return Promise.reject(
          new ApiError("Request failed (409)", 409, {
            detail: {
              code: "plan_limit_reached",
              resource: "webhooks",
              used: 1,
              limit: 1,
              plan: { id: "plan-1", code: "free", name: "Free" },
              message: "You've reached your plan's limit for webhooks.",
            },
          })
        );
      }
      return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(screen.getByText("https://example.com/hook")).toBeInTheDocument());

    await user.type(screen.getByLabelText(/Endpoint URL/), "https://example.com/new-hook");
    await user.click(screen.getByLabelText("Customer created"));
    await user.click(screen.getByRole("button", { name: "Add endpoint" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("You've reached your plan's limit for Webhooks.")).toBeInTheDocument();
  });

  it("rotates the secret after confirmation and shows the new secret once", async () => {
    const rotated: WebhookEndpointCreated = { ...existingEndpoint, secret: "whsec_rotatedvalue" };
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/webhooks") && method === "GET") return Promise.resolve([existingEndpoint]);
      if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
      if (path.includes("/rotate-secret")) return Promise.resolve(rotated);
      return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(screen.getByText("https://example.com/hook")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Rotate secret"));

    expect(await screen.findByText("whsec_rotatedvalue")).toBeInTheDocument();
  });

  it("disables an endpoint", async () => {
    let disabled = false;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/webhooks") && method === "GET") {
        return Promise.resolve([{ ...existingEndpoint, enabled: !disabled }]);
      }
      if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
      if (path.includes("/disable")) {
        disabled = true;
        return Promise.resolve({ ...existingEndpoint, enabled: false });
      }
      return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(screen.getByText("https://example.com/hook")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Disable"));

    await waitFor(() => expect(screen.getByText("Disabled")).toBeInTheDocument());
  });

  it("archives an endpoint after confirmation", async () => {
    let archived = false;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/webhooks") && method === "GET") {
        return Promise.resolve(archived ? [] : [existingEndpoint]);
      }
      if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
      if (method === "DELETE") {
        archived = true;
        return Promise.resolve({ ...existingEndpoint, active: false });
      }
      return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(screen.getByText("https://example.com/hook")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Archive"));

    await waitFor(() => expect(screen.getByText("No webhook endpoints yet")).toBeInTheDocument());
  });

  it("shows delivery history and allows resending a delivery", async () => {
    const deliveries: PaginatedWebhookDeliveries = {
      total: 1,
      items: [
        {
          id: "del-1",
          organization_id: "org-1",
          event_id: "evt-1",
          endpoint_id: "ep-1",
          status: "failed",
          trigger: "automatic",
          attempt_number: 1,
          request_url: "https://example.com/hook",
          response_status_code: 500,
          response_body_snippet: "server error",
          error_message: null,
          duration_ms: 120,
          attempted_at: "2026-01-02T00:00:00Z",
          next_retry_at: null,
          created_at: "2026-01-02T00:00:00Z",
        },
      ],
    };
    let resent = false;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (path.endsWith("/webhooks") && method === "GET") return Promise.resolve([existingEndpoint]);
      if (path.endsWith("/webhooks/event-types")) return Promise.resolve(catalog);
      if (path.endsWith("/deliveries") && method === "GET") return Promise.resolve(deliveries);
      if (path.includes("/resend")) {
        resent = true;
        return Promise.resolve({ ...deliveries.items[0], id: "del-2", trigger: "manual_resend" });
      }
      return Promise.reject(new Error(`unexpected call: ${path} ${method}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<WebhooksPage />);
    await waitFor(() => expect(screen.getByText("https://example.com/hook")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("View deliveries"));

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    await user.click(screen.getByText("Resend"));
    await waitFor(() => expect(resent).toBe(true));
  });
});
