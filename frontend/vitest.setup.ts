import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// Without vitest's `globals: true`, @testing-library/react can't
// auto-detect the test framework's afterEach hook to register its own
// DOM cleanup -- without this, every test in a file renders into the same
// jsdom document, and later tests see leftover elements from earlier ones
// (e.g. duplicate "Open menu" buttons).
afterEach(() => {
  cleanup();
});

// jsdom doesn't implement HTMLDialogElement.showModal()/close() -- both are
// used by AppShell's mobile nav (see components/layout/AppShell.tsx). This
// polyfill toggles the `open` attribute and dispatches the same `close`
// event the browser would, which is all AppShell's own event listener
// depends on.
if (typeof HTMLDialogElement !== "undefined") {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    const wasOpen = this.hasAttribute("open");
    this.removeAttribute("open");
    if (wasOpen) {
      this.dispatchEvent(new Event("close"));
    }
  };
}

// jsdom has no scrollIntoView implementation -- harmless no-op is enough
// for any component that calls it during a test (e.g. auto-scrolling
// chat views).
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
