import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import { ToastProvider } from "@/components/ui/toast";

// app/providers.tsx only ever mounts <ToastProvider> globally -- no
// router/theme/query-client context exists in this app. useToast() throws
// outside it, so any component under test that calls it needs this
// wrapper. next/navigation hooks (usePathname/useRouter/useSearchParams)
// are NOT provided here -- mock them per-test-file with vi.mock, since
// their needed return values vary per test.
function AllProviders({ children }: { children: ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

export function renderWithProviders(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: AllProviders, ...options });
}

export * from "@testing-library/react";
