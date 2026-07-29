import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { setAuthSession } from "@/lib/auth-storage";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";
import { renderWithProviders } from "@/tests/test-utils";

import ApiKeysPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/api-keys",
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const existingKey: ApiKey = {
  id: "key-1",
  organization_id: "org-1",
  name: "Order sync",
  description: "Used by the order sync worker",
  prefix: "abc123prefix",
  permissions: ["customers.read", "invoices.write"],
  status: "active",
  created_by: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  expires_at: null,
  last_used_at: null,
  last_used_ip: null,
  revoked_at: null,
  revoked_by: null,
};

function mockKeysList(keys: ApiKey[]) {
  apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path.endsWith("/api-keys") && (!init || init.method === undefined)) {
      return Promise.resolve(keys);
    }
    return Promise.reject(new Error(`unexpected call: ${path} ${init?.method ?? "GET"}`));
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

describe("ApiKeysPage", () => {
  it("renders the existing keys without ever showing a secret", async () => {
    mockKeysList([existingKey]);
    renderWithProviders(<ApiKeysPage />);

    await waitFor(() => expect(screen.getByText("Order sync")).toBeInTheDocument());
    expect(screen.getByText("Active")).toBeInTheDocument();
    // Only the masked "sk_{prefix}_…" identifier is ever shown for an
    // existing key -- never the full secret (which only ever exists in
    // the one-time creation/rotation response, not on this list).
    expect(screen.getByText("sk_", { exact: false })).toHaveTextContent(`sk_${existingKey.prefix}_…`);
  });

  it("shows an empty state when there are no keys", async () => {
    mockKeysList([]);
    renderWithProviders(<ApiKeysPage />);

    await waitFor(() =>
      expect(screen.getByText("No API keys yet. Create one above to start calling the public API.")).toBeInTheDocument()
    );
  });

  it("requires a name and at least one permission before submitting", async () => {
    mockKeysList([]);
    const user = userEvent.setup();
    renderWithProviders(<ApiKeysPage />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Create API key" }));
    expect(await screen.findByText("Select at least one permission.")).toBeInTheDocument();
  });

  it("creates a key and shows the one-time secret dialog", async () => {
    const created: ApiKeyCreated = { ...existingKey, id: "key-2", api_key: "sk_newprefix123_supersecretvalue" };
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/api-keys") && (!init || init.method === undefined)) {
        return Promise.resolve([]);
      }
      if (path.endsWith("/api-keys") && init?.method === "POST") {
        return Promise.resolve(created);
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<ApiKeysPage />);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/Name/), "New integration");
    await user.click(screen.getByLabelText("Customers: Read"));
    await user.click(screen.getByRole("button", { name: "Create API key" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("sk_newprefix123_supersecretvalue")).toBeInTheDocument();
    expect(screen.queryByText(/upgrade/i)).not.toBeInTheDocument();
  });

  it("shows the plan-limit dialog when the API key quota is reached (409 plan_limit_reached)", async () => {
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/api-keys") && (!init || init.method === undefined)) {
        return Promise.resolve([existingKey]);
      }
      if (path.endsWith("/api-keys") && init?.method === "POST") {
        return Promise.reject(
          new ApiError("Request failed (409)", 409, {
            detail: {
              code: "plan_limit_reached",
              resource: "api_keys",
              used: 1,
              limit: 1,
              plan: { id: "plan-1", code: "free", name: "Free" },
              message: "You've reached your plan's limit for API keys.",
            },
          })
        );
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });

    const user = userEvent.setup();
    renderWithProviders(<ApiKeysPage />);
    await waitFor(() => expect(screen.getByText("Order sync")).toBeInTheDocument());

    await user.type(screen.getByLabelText(/Name/), "Second integration");
    await user.click(screen.getByLabelText("Customers: Read"));
    await user.click(screen.getByRole("button", { name: "Create API key" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("You've reached your plan's limit for API keys.")).toBeInTheDocument();
  });

  it("rotates a key after confirmation and shows the new secret once", async () => {
    const rotated: ApiKeyCreated = { ...existingKey, api_key: "sk_rotatedprefix1_rotatedsecretvalue" };
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/api-keys") && (!init || init.method === undefined)) {
        return Promise.resolve([existingKey]);
      }
      if (path.includes("/rotate")) {
        return Promise.resolve(rotated);
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWithProviders(<ApiKeysPage />);
    await waitFor(() => expect(screen.getByText("Order sync")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Rotate"));

    expect(await screen.findByText("sk_rotatedprefix1_rotatedsecretvalue")).toBeInTheDocument();
  });

  it("revokes a key after confirmation", async () => {
    let revokeCalled = false;
    apiFetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.endsWith("/api-keys") && (!init || init.method === undefined)) {
        return Promise.resolve(revokeCalled ? [{ ...existingKey, status: "revoked" as const }] : [existingKey]);
      }
      if (path.includes("/revoke")) {
        revokeCalled = true;
        return Promise.resolve({ ...existingKey, status: "revoked" });
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWithProviders(<ApiKeysPage />);
    await waitFor(() => expect(screen.getByText("Order sync")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Revoke"));

    await waitFor(() => expect(screen.getByText("Revoked")).toBeInTheDocument());
  });

  it("does not call revoke when the confirmation is declined", async () => {
    mockKeysList([existingKey]);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    const user = userEvent.setup();
    renderWithProviders(<ApiKeysPage />);
    await waitFor(() => expect(screen.getByText("Order sync")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByText("Revoke"));

    apiFetchMock.mockClear();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(apiFetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/revoke"), expect.anything());
  });
});
