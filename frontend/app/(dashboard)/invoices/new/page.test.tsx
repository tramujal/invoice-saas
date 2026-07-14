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
