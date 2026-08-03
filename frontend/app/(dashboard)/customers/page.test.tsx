import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Customer, CustomerDuplicateCheckResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import CustomersPage from "./page";

const apiFetchMock = vi.fn();
const apiFetchBlobMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
    apiFetchBlob: (...args: unknown[]) => apiFetchBlobMock(...args),
  };
});

const existingCustomer: Customer = {
  id: "cust-existing-1",
  organization_id: "org-1",
  name: "Estudio Creativo Delta",
  email: "contacto@estudiodelta.com",
  phone: "",
  address: "",
  tax_id: "123456789",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const blockingResult: CustomerDuplicateCheckResponse = {
  severity: "blocking",
  matches: [
    {
      customer_id: existingCustomer.id,
      customer_name: existingCustomer.name,
      email: "",
      phone: "",
      tax_id: existingCustomer.tax_id,
      reasons: ["tax_id"],
    },
  ],
};

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
  apiFetchBlobMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "owner@example.com",
  });
});

describe("CustomersPage -- 'Open existing customer' shortcut (Phase UX5)", () => {
  it("opens the matched customer inline for editing, without navigating away or losing the workflow", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(blockingResult);
      if (path.startsWith("/organizations/org-1/customers?")) return Promise.resolve([existingCustomer]);
      return Promise.resolve({ id: "unused" });
    });

    const user = userEvent.setup();
    renderWithProviders(<CustomersPage />);

    await waitFor(() => expect(screen.getByText(existingCustomer.name)).toBeInTheDocument());

    await user.type(screen.getByLabelText(/Name/), "Estudio Creativo Delta 2");
    await user.type(screen.getByLabelText(/Email/), "otro@example.com");
    await user.type(screen.getByLabelText(/Tax ID/), "123456789");
    await user.click(screen.getByRole("button", { name: "Create customer" }));

    await user.click(await screen.findByRole("button", { name: "Open existing customer" }));

    expect(await screen.findByText("Edit customer")).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/)).toHaveValue(existingCustomer.name);
    expect(screen.getByLabelText(/Email/)).toHaveValue(existingCustomer.email);
    // Never closed the workflow unexpectedly -- the form is still right
    // there, now populated with the existing customer instead of vanishing.
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
