import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Customer, PaginatedProducts, Product } from "@/lib/types";
import { renderWithProviders, screen, waitFor, within } from "@/tests/test-utils";

import NewInvoicePage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  };
});

function makeProduct(overrides: Partial<Product>): Product {
  return {
    id: "product-1",
    organization_id: "org-1",
    name: "Hosting",
    description: "",
    type: "service",
    sku: "",
    default_unit_price: "15.00",
    currency_code: "USD",
    default_tax_rate: "0",
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as Product;
}

const noCustomers: Customer[] = [];

function mockProductsResponse(products: Product[]) {
  apiFetchMock.mockImplementation((path: string) => {
    if (String(path).includes("/customers")) return Promise.resolve(noCustomers);
    if (String(path).includes("/products")) {
      return Promise.resolve({ total: products.length, items: products } satisfies PaginatedProducts);
    }
    return Promise.reject(new Error(`unexpected call: ${path}`));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
    userEmail: "self@example.com",
  });
});

describe("New Invoice page — product-first currency flow", () => {
  it("has no currency badge and shows an empty state before any line is added", () => {
    mockProductsResponse([]);
    renderWithProviders(<NewInvoicePage />);
    expect(screen.queryByText(/Currency:/)).not.toBeInTheDocument();
    expect(screen.getByText(/No line items yet/)).toBeInTheDocument();
  });

  it("adding a product line sets the document currency", async () => {
    mockProductsResponse([makeProduct({ currency_code: "USD" })]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() => expect(screen.getByText("Hosting")).toBeInTheDocument());
    await user.click(screen.getByRole("option", { name: /Hosting/ }));

    await waitFor(() => expect(screen.getByText(/Currency: USD/)).toBeInTheDocument());
  });

  it("blocks selecting an incompatible-currency product once currency is set", async () => {
    mockProductsResponse([makeProduct({ currency_code: "USD" })]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() => expect(screen.getByText("Hosting")).toBeInTheDocument());
    await user.click(screen.getByRole("option", { name: /Hosting/ }));
    await waitFor(() => expect(screen.getByText(/Currency: USD/)).toBeInTheDocument());

    mockProductsResponse([makeProduct({ id: "product-2", name: "Consulting EU", currency_code: "EUR" })]);
    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() => expect(screen.getByText("Consulting EU")).toBeInTheDocument());
    const option = screen.getByRole("option", { name: /Consulting EU/ });
    expect(option).toBeDisabled();
  });

  it("removing the only line resets the currency badge", async () => {
    mockProductsResponse([makeProduct({ currency_code: "USD" })]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() => expect(screen.getByText("Hosting")).toBeInTheDocument());
    await user.click(screen.getByRole("option", { name: /Hosting/ }));
    await waitFor(() => expect(screen.getByText(/Currency: USD/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByText(/Currency:/)).not.toBeInTheDocument());
    expect(screen.getByText(/No line items yet/)).toBeInTheDocument();
  });

  it("adding a manual line first shows a currency prompt", async () => {
    mockProductsResponse([]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() =>
      expect(screen.getByText("➕ Create Manual Line")).toBeInTheDocument()
    );
    await user.click(screen.getByRole("option", { name: /Create Manual Line/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("combobox")).toBeInTheDocument();
  });

});

/** Regression coverage for a real bug: ManualLineEditor is portal-rendered
 * via createPortal into document.body, outside this page's own <form> in
 * the DOM. React bubbles synthetic events through the REACT tree rather
 * than the DOM tree for portaled content, so without stopPropagation on
 * the portal's own form submit, adding a manual line was also triggering
 * THIS page's outer onSubmit -- silently creating the invoice with
 * whatever line had just been added, before the user ever clicked
 * "Create invoice". Fixed in ManualLineEditor.handleSubmit. */
function invoicePostCalls(calls: unknown[][]): unknown[][] {
  return calls.filter(
    (call) =>
      String(call[0]) === "/organizations/org-1/invoices" &&
      (call[1] as { method?: string } | undefined)?.method === "POST"
  );
}

async function addManualLine(
  user: ReturnType<typeof userEvent.setup>,
  description: string,
  price: string
) {
  await user.click(screen.getByRole("button", { name: "+ Add line" }));
  await waitFor(() => expect(screen.getByText("➕ Create Manual Line")).toBeInTheDocument());
  await user.click(screen.getByRole("option", { name: /Create Manual Line/ }));
  const dialog = await screen.findByRole("dialog");
  const descInput = within(dialog).getByPlaceholderText(/description/i);
  await user.type(descInput, description);
  const numberInputs = within(dialog).getAllByRole("spinbutton");
  await user.clear(numberInputs[1]);
  await user.type(numberInputs[1], price);
  await user.click(within(dialog).getByRole("button", { name: /add line/i }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

describe("New Invoice page — manual line never prematurely submits (regression)", () => {
  it("adding the first manual line does not submit the invoice", async () => {
    mockProductsResponse([]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await addManualLine(user, "Line one", "100");
    await waitFor(() => expect(screen.getByDisplayValue("Line one")).toBeInTheDocument());

    expect(invoicePostCalls(apiFetchMock.mock.calls)).toHaveLength(0);
  });

  it("adding a second manual line does not submit the invoice", async () => {
    mockProductsResponse([]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await addManualLine(user, "Line one", "100");
    await waitFor(() => expect(screen.getByDisplayValue("Line one")).toBeInTheDocument());
    await addManualLine(user, "Line two", "200");
    await waitFor(() => expect(screen.getByDisplayValue("Line two")).toBeInTheDocument());

    expect(screen.getByDisplayValue("Line one")).toBeInTheDocument();
    expect(invoicePostCalls(apiFetchMock.mock.calls)).toHaveLength(0);
  });

  it("editing a line does not submit the invoice", async () => {
    mockProductsResponse([]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await addManualLine(user, "Line one", "100");
    const descField = await screen.findByDisplayValue("Line one");
    await user.clear(descField);
    await user.type(descField, "Line one, edited");

    await waitFor(() => expect(screen.getByDisplayValue("Line one, edited")).toBeInTheDocument());
    expect(invoicePostCalls(apiFetchMock.mock.calls)).toHaveLength(0);
  });

  it("removing a line does not submit the invoice", async () => {
    mockProductsResponse([]);
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await addManualLine(user, "Line one", "100");
    await screen.findByDisplayValue("Line one");
    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(screen.getByText(/No line items yet/)).toBeInTheDocument());
    expect(invoicePostCalls(apiFetchMock.mock.calls)).toHaveLength(0);
  });

  it("only the explicit Create Invoice action submits, and exactly once", async () => {
    mockProductsResponse([]);
    apiFetchMock.mockImplementation((path: string, init?: { method?: string }) => {
      if (String(path).includes("/customers")) return Promise.resolve(noCustomers);
      if (String(path).includes("/products")) {
        return Promise.resolve({ total: 0, items: [] } satisfies PaginatedProducts);
      }
      if (path === "/organizations/org-1/invoices" && init?.method === "POST") {
        return Promise.resolve({ id: "invoice-1", invoice_number: "INV-000001" });
      }
      return Promise.reject(new Error(`unexpected call: ${path}`));
    });
    const user = userEvent.setup();
    renderWithProviders(<NewInvoicePage />);

    await addManualLine(user, "Line one", "100");
    await screen.findByDisplayValue("Line one");
    expect(invoicePostCalls(apiFetchMock.mock.calls)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Create invoice" }));

    await waitFor(() => expect(invoicePostCalls(apiFetchMock.mock.calls)).toHaveLength(1));
  });
});
