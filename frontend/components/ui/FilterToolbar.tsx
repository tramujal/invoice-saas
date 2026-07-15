"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { FilterChip } from "@/components/ui/FilterChip";
import { Input } from "@/components/ui/Input";

export type ActiveFilterChip = {
  key: string;
  label: string;
  removeLabel: string;
  onRemove: () => void;
};

type FilterToolbarProps = {
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  searchAriaLabel: string;
  /** The page's own filter controls (selects, number inputs, SortControl).
   * Rendered once; a CSS-only breakpoint toggle shows them inline on
   * desktop and behind the "Filters" trigger on mobile -- no portal, no
   * duplicate DOM, since a toolbar trigger (unlike RowActionsMenu) isn't
   * inside a clipped scroll container that would need one. */
  children: ReactNode;
  onReset: () => void;
  resetLabel: string;
  isDefaultState: boolean;
  filtersLabel: string;
  chips?: ActiveFilterChip[];
};

export function FilterToolbar({
  searchValue,
  onSearchChange,
  searchPlaceholder,
  searchAriaLabel,
  children,
  onReset,
  resetLabel,
  isDefaultState,
  filtersLabel,
  chips = [],
}: FilterToolbarProps) {
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <label htmlFor="filter-toolbar-search" className="sr-only">
            {searchAriaLabel}
          </label>
          <Input
            id="filter-toolbar-search"
            type="search"
            value={searchValue}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
          />
        </div>

        <div className="shrink-0 sm:hidden">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setMobileFiltersOpen((open) => !open)}
            aria-expanded={mobileFiltersOpen}
          >
            {filtersLabel}
            {chips.length > 0 ? (
              <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-slate-900 px-1 text-[10px] font-semibold text-white">
                {chips.length}
              </span>
            ) : null}
          </Button>
        </div>
      </div>

      <div
        className={`${mobileFiltersOpen ? "flex" : "hidden"} mt-3 flex-wrap items-center gap-3 sm:flex`}
      >
        {children}
        <Button type="button" variant="secondary" size="sm" onClick={onReset} disabled={isDefaultState}>
          {resetLabel}
        </Button>
      </div>

      {chips.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          {chips.map((chip) => (
            <FilterChip
              key={chip.key}
              label={chip.label}
              removeLabel={chip.removeLabel}
              onRemove={chip.onRemove}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
