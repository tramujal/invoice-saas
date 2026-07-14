import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import type { Customer, PaginatedProducts, Product, Quote } from "@/lib/types";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import { QuoteForm } from "./QuoteForm";

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

function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: "quote-1",
    quote_number: "QUO-000001",
    organization_id: "org-1",
    created_by_user_id: "user-1",
    customer_id: null,
    customer_name: null,
    subtotal: "100.00",
    tax_rate: "0",
    tax_amount: "0.00",
    total: "100.00",
    status: "draft" as Quote["status"],
    effective_status: "draft" as Quote["effective_status"],
    currency_code: "EUR",
    language: "en",
    issue_date: "2026-01-01",
    expiry_date: null,
    notes: "",
    active: true,
    converted_invoice_id: null,
    public_url: "https://example.com/quotes/public/abc",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    line_items: [
      {
        id: "li-1",
        description: "Consulting",
        quantity: "1",
        unit_price: "100.00",
        line_total: "100.00",
        product_id: "product-eur",
      },
    ],
    ...overrides,
  };
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

describe("QuoteForm — create mode", () => {
  it("adding a product line sets the document currency", async () => {
    mockProductsResponse([makeProduct({ currency_code: "USD" })]);
    const user = userEvent.setup();
    renderWithProviders(
      <QuoteForm mode="create" backHref="/quotes" onSubmit={vi.fn()} isSubmitting={false} />
    );

    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() => expect(screen.getByText("Hosting")).toBeInTheDocument());
    await user.click(screen.getByRole("option", { name: /Hosting/ }));

    await waitFor(() => expect(screen.getByText(/Currency: USD/)).toBeInTheDocument());
  });
});

describe("QuoteForm — edit mode", () => {
  it("shows the quote's pinned currency for a pre-existing product-linked line without a preloaded product cache", async () => {
    // The picker's search endpoint is never even called for the initial
    // render -- the seeded line's currency comes directly from
    // initialQuote.currency_code, not a live product lookup.
    mockProductsResponse([]);
    const quote = makeQuote({ currency_code: "EUR" });

    renderWithProviders(
      <QuoteForm
        mode="edit"
        initialQuote={quote}
        backHref="/quotes"
        onSubmit={vi.fn()}
        isSubmitting={false}
      />
    );

    expect(screen.getByText(/Currency: EUR/)).toBeInTheDocument();
  });

  it("blocks adding an incompatible-currency product to an existing quote", async () => {
    mockProductsResponse([makeProduct({ id: "product-2", name: "Support", currency_code: "USD" })]);
    const quote = makeQuote({ currency_code: "EUR" });
    const user = userEvent.setup();

    renderWithProviders(
      <QuoteForm
        mode="edit"
        initialQuote={quote}
        backHref="/quotes"
        onSubmit={vi.fn()}
        isSubmitting={false}
      />
    );

    await user.click(screen.getByRole("button", { name: "+ Add line" }));
    await waitFor(() => expect(screen.getByText("Support")).toBeInTheDocument());
    expect(screen.getByRole("option", { name: /Support/ })).toBeDisabled();
  });
});
