import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/** Phase UX -- layout consistency guard.
 *
 * This deliberately does NOT assert on Tailwind class strings inside
 * PageContainer itself (jsdom does no layout, so such a test would only
 * restate the implementation). It asserts the ARCHITECTURAL invariant
 * this abstraction exists to enforce: every authenticated page delegates
 * its horizontal width to the shared container instead of declaring its
 * own.
 *
 * The regression it catches is concrete and likely: a new page (or a
 * copy-paste of an older one) reintroducing `mx-auto max-w-6xl`, which is
 * exactly how the app previously ended up with 32 pages disagreeing about
 * width and a narrow centered island on large monitors.
 */

const APP_DIR = path.join(process.cwd(), "app");

function pageFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...pageFiles(full));
    else if (entry.name === "page.tsx") out.push(full);
  }
  return out;
}

/** Authenticated route groups only -- the public marketing/auth pages
 * (login, reset-password, the public quote view) are standalone
 * full-screen layouts with no sidebar, and legitimately center a narrow
 * card of their own. */
function authenticatedPages(): string[] {
  return pageFiles(APP_DIR).filter(
    (f) => f.includes(`${path.sep}(dashboard)${path.sep}`) || f.includes(`${path.sep}(admin)${path.sep}`)
  );
}

/** Pages that legitimately do not reference PageContainer themselves.
 * Every entry needs a reason -- this list is where a deliberate layout
 * exception gets recorded, so it can't quietly become accidental drift. */
const EXCEPTIONS: Record<string, string> = {
  "quotes/new/page.tsx": "delegates its entire layout to <QuoteForm>, which uses PageContainer",
  "quotes/[id]/edit/page.tsx": "delegates its entire layout to <QuoteForm>, which uses PageContainer",
  "assistant/page.tsx":
    "deliberate CONTENT READABILITY WIDTH: a chat transcript stays at a comfortable " +
    "line length instead of stretching across an ultrawide monitor, and it needs a " +
    "full-height flex column rather than PageContainer's vertical spacing.",
};

function isException(file: string): boolean {
  const norm = file.split(path.sep).join("/");
  return Object.keys(EXCEPTIONS).some((suffix) => norm.endsWith(suffix));
}

describe("authenticated page layout", () => {
  it("finds the authenticated pages it is meant to be guarding", () => {
    // Guards the guard: if the route-group folders are ever renamed, this
    // suite must fail loudly rather than silently passing over zero files.
    expect(authenticatedPages().length).toBeGreaterThan(25);
  });

  it("routes every authenticated page's width through PageContainer", () => {
    const offenders = authenticatedPages()
      .filter((f) => !isException(f))
      .filter((f) => !fs.readFileSync(f, "utf8").includes("PageContainer"));
    expect(
      offenders.map((f) => path.relative(process.cwd(), f)),
      "these pages don't use the shared PageContainer -- add it, or record a reason in EXCEPTIONS"
    ).toEqual([]);
  });

  it("keeps every documented exception real", () => {
    // If an exception's page is deleted or renamed, the entry must be
    // cleaned up rather than lingering as stale permission.
    const pages = authenticatedPages().map((f) => f.split(path.sep).join("/"));
    for (const suffix of Object.keys(EXCEPTIONS)) {
      expect(
        pages.some((p) => p.endsWith(suffix)),
        `EXCEPTIONS lists "${suffix}" but no such page exists anymore`
      ).toBe(true);
    }
  });

  it("keeps page-level max-width out of individual pages", () => {
    // A page-level `mx-auto max-w-*` is the exact pattern that produced
    // the narrow-centered-island problem. Inner ones (a centered loading
    // card, a constrained field group) are fine and common, so this only
    // rejects the wrapper that directly follows `return (`.
    const offenders: string[] = [];
    for (const file of authenticatedPages()) {
      const src = fs.readFileSync(file, "utf8");
      if (/return \(\s*<div className="mx-auto max-w-/.test(src)) {
        offenders.push(path.relative(process.cwd(), file));
      }
    }
    expect(
      offenders,
      "these pages cap their own width instead of using PageContainer's width variants"
    ).toEqual([]);
  });
});
