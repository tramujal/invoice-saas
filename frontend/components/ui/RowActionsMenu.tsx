"use client";

import Link from "next/link";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

// Rendered as a portal to document.body rather than an absolutely-positioned
// child of the table cell: the actions column sits inside a horizontally
// (and therefore, per the CSS overflow spec, implicitly vertically too)
// clipped `overflow-x-auto` table wrapper -- a non-portaled dropdown would
// get cut off the moment it extended past that wrapper's box. Position is
// computed from the trigger's own bounding rect on open, matching how
// Stripe/GitHub/Linear detach their row-action menus from any scroll
// container.

const MENU_GAP_PX = 6;
const VIEWPORT_MARGIN_PX = 8;

// Shared styling for the pinned actions column across every table that
// uses RowActionsMenu (Customers/Products/Quotes/Invoices/Team) -- kept
// here so the column and its trigger stay visually/behaviorally in sync.
// The left-edge shadow signals the sticky boundary while horizontally
// scrolling, matching the "pinned column" affordance in Stripe/GitHub/
// Linear's own tables. Pair the <td> with `group` on the owning <tr> and
// its own `hover:bg-slate-50/80` so the sticky cell's opaque background
// (required so scrolled-under content doesn't show through) still
// participates in the row's hover state via group-hover.
export const STICKY_ACTIONS_TH_CLASS =
  "sticky right-0 z-10 bg-slate-50 px-4 py-2.5 text-right sm:px-6";
export const STICKY_ACTIONS_TD_CLASS =
  "sticky right-0 z-10 bg-white px-4 py-2.5 text-right shadow-[-8px_0_8px_-8px_rgba(15,23,42,0.12)] group-hover:bg-slate-50 sm:px-6";

type MenuContextValue = {
  close: () => void;
};

const MenuContext = createContext<MenuContextValue | null>(null);

function useMenuContext(componentName: string): MenuContextValue {
  const ctx = useContext(MenuContext);
  if (!ctx) {
    throw new Error(`${componentName} must be rendered inside a <RowActionsMenu>`);
  }
  return ctx;
}

type Placement = { top: number; left: number; placedAbove: boolean };

function computePlacement(trigger: HTMLElement, menu: HTMLElement): Placement {
  const triggerRect = trigger.getBoundingClientRect();
  const menuRect = menu.getBoundingClientRect();

  // Right-align the panel to the trigger's right edge -- this is the
  // rightmost pinned column, so left-aligning would routinely push the
  // panel off the right edge of the viewport.
  let left = triggerRect.right - menuRect.width;
  left = Math.max(
    VIEWPORT_MARGIN_PX,
    Math.min(left, window.innerWidth - menuRect.width - VIEWPORT_MARGIN_PX)
  );

  const spaceBelow = window.innerHeight - triggerRect.bottom;
  const placedAbove = spaceBelow < menuRect.height + MENU_GAP_PX && triggerRect.top > spaceBelow;

  const top = placedAbove
    ? triggerRect.top - menuRect.height - MENU_GAP_PX
    : triggerRect.bottom + MENU_GAP_PX;

  return { top: Math.max(VIEWPORT_MARGIN_PX, top), left, placedAbove };
}

function focusableMenuItems(menu: HTMLElement): HTMLElement[] {
  return Array.from(
    menu.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')
  );
}

type RowActionsMenuProps = {
  /** Accessible name for the trigger button, e.g. t("common.moreActions"). */
  label: string;
  children: ReactNode;
};

export function RowActionsMenu({ label, children }: RowActionsMenuProps) {
  const [open, setOpen] = useState(false);
  // Two-phase render: the panel first renders off-screen (visibility:
  // hidden) so its real dimensions can be measured, then it's placed and
  // revealed -- avoids a visible flash at the wrong position for a panel
  // whose height depends on how many items it has.
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [mounted, setMounted] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  function close() {
    setOpen(false);
    setPlacement(null);
  }

  function openMenu() {
    setPlacement(null);
    setOpen(true);
  }

  useLayoutEffect(() => {
    if (!open || placement) return;
    const trigger = triggerRef.current;
    const menu = menuRef.current;
    if (!trigger || !menu) return;
    setPlacement(computePlacement(trigger, menu));
  }, [open, placement]);

  // Focuses the first (or last, for ArrowUp-opened) item only once the
  // panel has actually been placed -- focusing before that would focus an
  // element still sitting at its pre-measurement offscreen position.
  const focusOnPlaceRef = useRef<"first" | "last" | null>(null);
  useEffect(() => {
    if (!placement || !menuRef.current) return;
    const target = focusOnPlaceRef.current;
    focusOnPlaceRef.current = null;
    if (!target) return;
    const items = focusableMenuItems(menuRef.current);
    if (items.length === 0) return;
    (target === "first" ? items[0] : items[items.length - 1]).focus();
  }, [placement]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(e: PointerEvent) {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      close();
    }
    // Scroll of *any* ancestor (capture: true catches the table's own
    // overflow-x-auto wrapper, not just window) invalidates the computed
    // position -- closing rather than re-measuring on every scroll frame
    // keeps this cheap, matching the behavior of most production row-menus.
    function handleScrollOrResize() {
      close();
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("scroll", handleScrollOrResize, true);
    window.addEventListener("resize", handleScrollOrResize);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("scroll", handleScrollOrResize, true);
      window.removeEventListener("resize", handleScrollOrResize);
      document.removeEventListener("keydown", handleKeyDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function handleTriggerKeyDown(e: React.KeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      focusOnPlaceRef.current = "first";
      openMenu();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      focusOnPlaceRef.current = "last";
      openMenu();
    }
  }

  function handleMenuKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const menu = menuRef.current;
    if (!menu) return;
    const items = focusableMenuItems(menu);
    if (items.length === 0) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(currentIndex + 1 + items.length) % items.length].focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(currentIndex - 1 + items.length) % items.length].focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      items[0].focus();
    } else if (e.key === "End") {
      e.preventDefault();
      items[items.length - 1].focus();
    } else if (e.key === "Tab") {
      // Native tab order, but the panel must not linger open once focus
      // leaves it.
      close();
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={handleTriggerKeyDown}
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden
        >
          <circle cx="12" cy="5" r="1.75" />
          <circle cx="12" cy="12" r="1.75" />
          <circle cx="12" cy="19" r="1.75" />
        </svg>
      </button>

      {mounted && open
        ? createPortal(
            <div
              ref={menuRef}
              role="menu"
              aria-label={label}
              onKeyDown={handleMenuKeyDown}
              style={{
                position: "fixed",
                top: placement?.top ?? -9999,
                left: placement?.left ?? -9999,
                visibility: placement ? "visible" : "hidden",
              }}
              className="z-50 min-w-[180px] rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-lg ring-1 ring-black/5"
            >
              <MenuContext.Provider value={{ close }}>{children}</MenuContext.Provider>
            </div>,
            document.body
          )
        : null}
    </>
  );
}

type RowActionsMenuItemProps = {
  children: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  destructive?: boolean;
  /** Native tooltip explaining why the item is disabled (e.g. missing data
   * or permission) -- only meaningful paired with disabled. */
  title?: string;
};

function itemClassName(destructive?: boolean): string {
  return `block w-full px-3 py-2 text-left text-sm outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
    destructive
      ? "text-red-700 hover:bg-red-50 focus:bg-red-50"
      : "text-slate-800 hover:bg-slate-50 focus:bg-slate-50"
  }`;
}

function RowActionsMenuItem({
  children,
  onSelect,
  disabled,
  destructive,
  title,
}: RowActionsMenuItemProps) {
  const { close } = useMenuContext("RowActionsMenu.Item");

  return (
    <button
      type="button"
      role="menuitem"
      aria-disabled={disabled || undefined}
      disabled={disabled}
      title={title}
      tabIndex={-1}
      onClick={() => {
        if (disabled) return;
        close();
        onSelect();
      }}
      className={itemClassName(destructive)}
    >
      {children}
    </button>
  );
}

type RowActionsMenuLinkItemProps = {
  children: ReactNode;
  href: string;
};

function RowActionsMenuLinkItem({ children, href }: RowActionsMenuLinkItemProps) {
  const { close } = useMenuContext("RowActionsMenu.LinkItem");

  return (
    <Link
      href={href}
      role="menuitem"
      tabIndex={-1}
      onClick={close}
      className={itemClassName(false)}
    >
      {children}
    </Link>
  );
}

RowActionsMenu.Item = RowActionsMenuItem;
RowActionsMenu.LinkItem = RowActionsMenuLinkItem;
