"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { apiFetch, orgPath } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type { CurrencyCode } from "@/lib/organization-settings";
import type { PaginatedProducts, Product } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

// Standalone positioning (measure-then-place, viewport-clamped, flips
// above when there's no room below) -- deliberately NOT sharing
// RowActionsMenu's computePlacement: that helper hardcodes right-alignment
// (wrong for a search panel, which should track its input's left edge) and
// closes on any capture-phase scroll, which would immediately close this
// panel the moment its own results list is scrolled. Modifying a shipped,
// tested, five-page-shared component for one new consumer isn't worth it
// here -- see the plan for this feature.
const PANEL_GAP_PX = 6;
const VIEWPORT_MARGIN_PX = 8;
const MANUAL_LINE_OPTION_ID = "product-picker-manual-line";

type Placement = { top: number; left: number; width: number };

function computePlacement(anchor: HTMLElement, panel: HTMLElement): Placement {
  const anchorRect = anchor.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();

  const width = Math.max(anchorRect.width, 320);
  let left = anchorRect.left;
  left = Math.max(
    VIEWPORT_MARGIN_PX,
    Math.min(left, window.innerWidth - width - VIEWPORT_MARGIN_PX)
  );

  const spaceBelow = window.innerHeight - anchorRect.bottom;
  const placedAbove = spaceBelow < panelRect.height + PANEL_GAP_PX && anchorRect.top > spaceBelow;
  const top = placedAbove
    ? anchorRect.top - panelRect.height - PANEL_GAP_PX
    : anchorRect.bottom + PANEL_GAP_PX;

  return { top: Math.max(VIEWPORT_MARGIN_PX, top), left, width };
}

function isCompatible(product: Product, documentCurrency: CurrencyCode | null): boolean {
  return documentCurrency === null || product.currency_code === documentCurrency;
}

type ProductPickerProps = {
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  documentCurrency: CurrencyCode | null;
  onClose: () => void;
  onSelectProduct: (product: Product) => void;
  onCreateManualLine: () => void;
};

export function ProductPicker({
  open,
  anchorRef,
  documentCurrency,
  onClose,
  onSelectProduct,
  onCreateManualLine,
}: ProductPickerProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 300);
  const [results, setResults] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const listboxId = "product-picker-listbox";

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setResults([]);
      setActiveId(null);
      setPlacement(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({ active: "true", limit: "20" });
    if (debouncedQuery.trim()) params.set("search", debouncedQuery.trim());
    apiFetch<PaginatedProducts>(`${orgPath("products")}?${params.toString()}`, {
      signal: controller.signal,
    })
      .then((res) => {
        setResults(res.items);
        setActiveId(res.items[0]?.id ?? MANUAL_LINE_OPTION_ID);
      })
      .catch((err) => {
        if ((err as { name?: string }).name === "AbortError") return;
        setResults([]);
        setActiveId(MANUAL_LINE_OPTION_ID);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [open, debouncedQuery]);

  useLayoutEffect(() => {
    if (!open || placement) return;
    const anchor = anchorRef.current;
    const panel = panelRef.current;
    if (!anchor || !panel) return;
    setPlacement(computePlacement(anchor, panel));
  }, [open, placement, anchorRef, results, loading]);

  useEffect(() => {
    if (open && placement) inputRef.current?.focus();
  }, [open, placement]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(e: PointerEvent) {
      const target = e.target as Node;
      if (anchorRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      onClose();
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose, anchorRef]);

  if (!open || !mounted) return null;

  const optionIds = [...results.map((p) => p.id), MANUAL_LINE_OPTION_ID];

  function moveActive(delta: 1 | -1) {
    const currentIndex = activeId ? optionIds.indexOf(activeId) : -1;
    const nextIndex = (currentIndex + delta + optionIds.length) % optionIds.length;
    setActiveId(optionIds[nextIndex]);
  }

  function selectActive() {
    if (activeId === MANUAL_LINE_OPTION_ID) {
      onCreateManualLine();
      return;
    }
    const product = results.find((p) => p.id === activeId);
    if (!product || !isCompatible(product, documentCurrency)) return;
    onSelectProduct(product);
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveActive(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveActive(-1);
    } else if (e.key === "Home") {
      e.preventDefault();
      setActiveId(optionIds[0] ?? null);
    } else if (e.key === "End") {
      e.preventDefault();
      setActiveId(optionIds[optionIds.length - 1] ?? null);
    } else if (e.key === "Enter") {
      e.preventDefault();
      selectActive();
    }
  }

  return createPortal(
    <div
      ref={panelRef}
      style={{
        position: "fixed",
        top: placement?.top ?? -9999,
        left: placement?.left ?? -9999,
        width: placement?.width,
        visibility: placement ? "visible" : "hidden",
      }}
      className="z-50 max-h-96 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg ring-1 ring-black/5"
    >
      <div className="border-b border-slate-100 p-2">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeId ?? undefined}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder={t("lineItemPicker.searchPlaceholder")}
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
        />
      </div>
      <div
        id={listboxId}
        role="listbox"
        aria-label={t("lineItemPicker.searchPlaceholder")}
        className="max-h-72 overflow-y-auto py-1"
      >
        {loading ? (
          <p className="px-3 py-2 text-sm text-slate-500">…</p>
        ) : results.length === 0 ? (
          <p className="px-3 py-2 text-sm text-slate-500">{t("lineItemPicker.noResults")}</p>
        ) : (
          results.map((product) => {
            const compatible = isCompatible(product, documentCurrency);
            return (
              <button
                key={product.id}
                id={product.id}
                type="button"
                role="option"
                aria-selected={activeId === product.id}
                aria-disabled={!compatible || undefined}
                disabled={!compatible}
                onMouseEnter={() => setActiveId(product.id)}
                onClick={() => compatible && onSelectProduct(product)}
                className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm outline-none ${
                  activeId === product.id ? "bg-slate-50" : ""
                } ${
                  compatible
                    ? "text-slate-800 hover:bg-slate-50"
                    : "cursor-not-allowed text-slate-400"
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{product.name}</span>
                <span className="shrink-0 text-xs">
                  {formatCurrency(product.default_unit_price, product.currency_code)}
                </span>
                {!compatible ? (
                  <span className="shrink-0 text-xs text-amber-700">
                    {t("lineItemPicker.incompatibleCurrency", {
                      currency: product.currency_code,
                    })}
                  </span>
                ) : null}
              </button>
            );
          })
        )}
        <button
          id={MANUAL_LINE_OPTION_ID}
          type="button"
          role="option"
          aria-selected={activeId === MANUAL_LINE_OPTION_ID}
          onMouseEnter={() => setActiveId(MANUAL_LINE_OPTION_ID)}
          onClick={onCreateManualLine}
          className={`block w-full border-t border-slate-100 px-3 py-2 text-left text-sm font-medium text-slate-700 outline-none hover:bg-slate-50 ${
            activeId === MANUAL_LINE_OPTION_ID ? "bg-slate-50" : ""
          }`}
        >
          {t("lineItemPicker.createManualLine")}
          <span className="block text-xs font-normal text-slate-500">
            {t("lineItemPicker.createManualLineHint")}
          </span>
        </button>
      </div>
    </div>,
    document.body
  );
}
