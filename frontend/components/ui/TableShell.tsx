/** Shared table-shell class constants, extracted from the recipe that was
 * previously hand-copied verbatim across invoices/quotes/customers/products
 * (and re-implemented differently, and inconsistently, on the team page).
 * Deliberately just class strings, matching this codebase's existing
 * convention for shared table styling (see RowActionsMenu.tsx's
 * STICKY_ACTIONS_TH_CLASS/STICKY_ACTIONS_TD_CLASS) rather than a wrapping
 * component -- header/row/footer content and structure varies enough per
 * page (some have pagination, some don't; some branch loading/empty state
 * inside <tbody>, some outside) that forcing them through one component
 * would need as many escape-hatch props as it saves lines. */

export const TABLE_WRAPPER_CLASS =
  "overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm";
export const TABLE_CLASS = "min-w-full divide-y divide-slate-200 text-left text-sm";
// Slightly darker header text than before (slate-600 -> slate-700) so column
// headers read as more distinct from body text at a glance.
export const TABLE_HEAD_CLASS =
  "bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-700";
export const TABLE_BODY_CLASS = "divide-y divide-slate-100";
export const TABLE_ROW_CLASS = "group transition-colors hover:bg-slate-50/80";
// Row padding reduced (py-3 -> py-2.5) per the "reduce row height slightly"
// brief -- still comfortably above the ~40px minimum tap-target guideline
// once combined with the 14px line-height text these cells hold.
export const TABLE_CELL_CLASS = "px-4 py-2.5 sm:px-6";
export const TABLE_HEAD_CELL_CLASS = "px-4 py-2.5 sm:px-6";
