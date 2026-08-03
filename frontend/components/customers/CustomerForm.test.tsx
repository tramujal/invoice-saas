import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Customer, CustomerDuplicateCheckResponse } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { CustomerForm } from "./CustomerForm";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

const noneResult: CustomerDuplicateCheckResponse = { severity: "none", matches: [] };

function warningResult(reasons: string[] = ["email"]): CustomerDuplicateCheckResponse {
  return {
    severity: "warning",
    matches: [
      {
        customer_id: "existing-1",
        customer_name: "Acme Existing",
        email: "shared@acme.com",
        phone: "",
        tax_id: "",
        reasons,
      },
    ],
  };
}

const blockingResult: CustomerDuplicateCheckResponse = {
  severity: "blocking",
  matches: [
    {
      customer_id: "existing-2",
      customer_name: "Acme Existing",
      email: "",
      phone: "",
      tax_id: "123456789",
      reasons: ["tax_id"],
    },
  ],
};

const suggestionResult: CustomerDuplicateCheckResponse = {
  severity: "suggestion",
  matches: [
    {
      customer_id: "existing-3",
      customer_name: "Juan Perez",
      email: "",
      phone: "",
      tax_id: "",
      reasons: ["name"],
    },
  ],
};

const existingCustomer: Customer = {
  id: "cust-edit-1",
  organization_id: "org-1",
  name: "Original Name",
  email: "original@example.com",
  phone: "111",
  address: "",
  tax_id: "999",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

async function fillCreateForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Name/), "New Customer");
  await user.type(screen.getByLabelText(/Email/), "new@example.com");
}

beforeEach(() => {
  window.localStorage.clear();
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "owner@example.com",
  });
});

describe("CustomerForm -- Phase UX5 duplicate detection", () => {
  it("creates immediately when the duplicate check returns 'none'", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(noneResult);
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    const createCall = apiFetchMock.mock.calls.find(([path]) => path === "/organizations/org-1/customers");
    expect(createCall).toBeTruthy();
  });

  it("stops and opens the warning dialog instead of creating -- never creates until 'Create anyway'", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(warningResult());
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    const createCall = apiFetchMock.mock.calls.find(([path]) => path === "/organizations/org-1/customers");
    expect(createCall).toBeFalsy();
  });

  it("'Create anyway' submits with duplicate_warning_acknowledged: true", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(warningResult());
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));
    await user.click(await screen.findByRole("button", { name: "Create anyway" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const createCall = apiFetchMock.mock.calls.find(([path]) => path === "/organizations/org-1/customers");
    expect(createCall).toBeTruthy();
    const body = JSON.parse((createCall![1] as { body: string }).body);
    expect(body.duplicate_warning_acknowledged).toBe(true);
  });

  it("blocking severity never offers a bypass and never creates", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(blockingResult);
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create anyway" })).not.toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    const createCall = apiFetchMock.mock.calls.find(([path]) => path === "/organizations/org-1/customers");
    expect(createCall).toBeFalsy();
  });

  it("'Open existing customer' calls onOpenExisting and never creates", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(blockingResult);
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const onOpenExisting = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} onOpenExisting={onOpenExisting} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));
    await user.click(await screen.findByRole("button", { name: "Open existing customer" }));

    expect(onOpenExisting).toHaveBeenCalledWith("existing-2");
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("Cancel closes the dialog without creating, and the form is still editable", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(warningResult());
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/Name/)).toHaveValue("New Customer");
  });

  it("suggestion severity never opens a dialog, shows a lightweight toast, and still creates immediately", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(suggestionResult);
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    // The toast fired *before* resetForm() clears the fields, so it's
    // still on screen (unlike an inline hint tied to the Name field,
    // which resetForm would wipe out immediately).
    expect(await screen.findByText(/Juan Perez/)).toBeInTheDocument();
  });

  it("edit flow: sends exclude_customer_id and blanks out unchanged fields", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.resolve(noneResult);
      return Promise.resolve(existingCustomer);
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm customer={existingCustomer} onSaved={onSaved} onCancel={vi.fn()} />);

    const phoneInput = screen.getByLabelText(/Phone/);
    await user.clear(phoneInput);
    await user.type(phoneInput, "222");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const checkCall = apiFetchMock.mock.calls.find(([path]) => path.endsWith("/check-duplicates"));
    expect(checkCall).toBeTruthy();
    const checkBody = JSON.parse((checkCall![1] as { body: string }).body);
    expect(checkBody.exclude_customer_id).toBe("cust-edit-1");
    // Unchanged fields (name, email, tax_id) are sent blank -- only the
    // actually-changed phone is checked.
    expect(checkBody.name).toBe("");
    expect(checkBody.email).toBe("");
    expect(checkBody.tax_id).toBe("");
    expect(checkBody.phone).toBe("222");
  });

  it("a failed duplicate check never blocks submission (falls through as if severity were 'none')", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith("/check-duplicates")) return Promise.reject(new Error("network error"));
      return Promise.resolve({ id: "new-1" });
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<CustomerForm onSaved={onSaved} />);

    await fillCreateForm(user);
    await user.click(screen.getByRole("button", { name: "Create customer" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
