import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthSession } from "@/lib/auth-storage";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

import AssistantPage from "./page";

const routerReplace = vi.fn();
const searchParamsGet = vi.fn().mockReturnValue(null);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
  useSearchParams: () => ({ get: searchParamsGet }),
}));

const apiFetchStreamMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiFetchStream: (...args: unknown[]) => apiFetchStreamMock(...args),
  };
});

/** Builds a fake streaming Response whose .body.getReader() yields the
 * given NDJSON lines one chunk at a time -- sidesteps real ReadableStream/
 * jsdom compatibility entirely, per the plan's documented approach. */
function fakeStreamResponse(lines: string[], opts: { signal?: AbortSignal } = {}) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    body: {
      getReader() {
        return {
          async read() {
            if (opts.signal?.aborted) {
              const err = new DOMException("Aborted", "AbortError");
              throw err;
            }
            if (index >= lines.length) {
              return { done: true, value: undefined };
            }
            const chunk = encoder.encode(lines[index] + "\n");
            index += 1;
            return { done: false, value: chunk };
          },
        };
      },
    },
  } as unknown as Response;
}

beforeEach(() => {
  window.localStorage.clear();
  routerReplace.mockClear();
  searchParamsGet.mockReturnValue(null);
  apiFetchStreamMock.mockReset();
  setAuthSession({
    token: "test-token",
    apiBaseUrl: "http://localhost:8000",
    organizationId: "org-1",
  });
});

describe("Assistant page", () => {
  it("sends a message and renders the streamed assistant reply", async () => {
    apiFetchStreamMock.mockResolvedValue(
      fakeStreamResponse([
        JSON.stringify({ type: "text_delta", text: "Hello" }),
        JSON.stringify({ type: "text_delta", text: " there" }),
      ])
    );
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);

    const textarea = screen.getByPlaceholderText("Ask about your business…");
    await user.type(textarea, "How am I doing?");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("How am I doing?")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Hello there")).toBeInTheDocument());
  });

  it("Clear is disabled with no messages and enabled once a conversation exists", async () => {
    apiFetchStreamMock.mockResolvedValue(fakeStreamResponse([JSON.stringify({ type: "text_delta", text: "Hi" })]));
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);

    expect(screen.getByRole("button", { name: "Clear conversation" })).toBeDisabled();

    const textarea = screen.getByPlaceholderText("Ask about your business…");
    await user.type(textarea, "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());

    const clearButton = screen.getByRole("button", { name: "Clear conversation" });
    expect(clearButton).not.toBeDisabled();
    await user.click(clearButton);
    expect(screen.queryByText("Hi")).not.toBeInTheDocument();
  });

  it("Stop aborts the in-flight stream", async () => {
    let capturedSignal: AbortSignal | undefined;
    // A reader whose read() never resolves on its own -- only rejects
    // once the abort signal fires -- simulating a still-streaming
    // response that Stop must actually cancel, not one that happens to
    // finish on its own first.
    apiFetchStreamMock.mockImplementation((_path: string, init?: RequestInit) => {
      capturedSignal = init?.signal ?? undefined;
      const response = {
        body: {
          getReader() {
            return {
              read() {
                return new Promise((_resolve, reject) => {
                  capturedSignal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                  });
                });
              },
            };
          },
        },
      } as unknown as Response;
      return Promise.resolve(response);
    });
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);

    const textarea = screen.getByPlaceholderText("Ask about your business…");
    await user.type(textarea, "slow question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const stopButton = await screen.findByRole("button", { name: "Stop generating" });
    await user.click(stopButton);

    expect(capturedSignal?.aborted).toBe(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument());
  });

  it("renders an action proposal card from an action_proposal event", async () => {
    apiFetchStreamMock.mockResolvedValue(
      fakeStreamResponse([
        JSON.stringify({
          type: "action_proposal",
          proposal_id: "proposal-xyz",
          action: "update_invoice_status",
          summary: { invoice_number: "INV-000001", old_status: "pending", new_status: "paid" },
          expires_at: new Date(Date.now() + 60_000).toISOString(),
        }),
      ])
    );
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);

    const textarea = screen.getByPlaceholderText("Ask about your business…");
    await user.type(textarea, "mark it paid");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("button", { name: "Confirm change" })).toBeInTheDocument();
  });
});
