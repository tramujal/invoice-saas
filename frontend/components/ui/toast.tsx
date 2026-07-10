"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useTranslation } from "@/lib/i18n/useTranslation";

export type ToastType = "success" | "error" | "loading";

export type ToastRecord = {
  id: string;
  type: ToastType;
  message: string;
  /** Auto-dismiss after ms; `undefined` uses type default; `null` disables. */
  duration: number | null;
};

export type ToastOptions = {
  /** Custom id (e.g. to dismiss a loading toast later). */
  id?: string;
  /** Override auto-dismiss; `null` = no auto-dismiss. */
  duration?: number | null;
};

const MAX_TOASTS = 5;
const DEFAULT_SUCCESS_MS = 6000;
const DEFAULT_ERROR_MS = 12_000;

function resolveDuration(type: ToastType, raw?: number | null): number | null {
  if (raw === null) return null;
  if (typeof raw === "number") return raw;
  if (type === "loading") return null;
  if (type === "success") return DEFAULT_SUCCESS_MS;
  return DEFAULT_ERROR_MS;
}

function newToastId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `toast-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type ToastContextValue = {
  toasts: ToastRecord[];
  success: (message: string, options?: ToastOptions) => string;
  error: (message: string, options?: ToastOptions) => string;
  loading: (message: string, options?: Pick<ToastOptions, "id">) => string;
  dismiss: (id: string) => void;
  dismissAll: () => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}

function toastRole(type: ToastType): "status" | "alert" {
  return type === "error" ? "alert" : "status";
}

function ToastIcon({ type }: { type: ToastType }) {
  if (type === "success") {
    return (
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      </span>
    );
  }
  if (type === "error") {
    return (
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </span>
    );
  }
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-700">
      <svg
        className="h-4 w-4 animate-spin"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
    </span>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: ToastRecord;
  onDismiss: (id: string) => void;
}) {
  const dismissButtonRef = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (toast.type === "loading") return;
    if (toast.duration === null) return;
    const id = toast.id;
    const ms = toast.duration;
    const timer = window.setTimeout(() => onDismiss(id), ms);
    return () => window.clearTimeout(timer);
  }, [toast.id, toast.type, toast.duration, onDismiss]);

  const border =
    toast.type === "success"
      ? "border-emerald-200/80"
      : toast.type === "error"
        ? "border-red-200/80"
        : "border-slate-200/90";

  return (
    <li
      role={toastRole(toast.type)}
      aria-atomic="true"
      className={`pointer-events-auto flex max-w-md animate-toast-in gap-3 rounded-xl border bg-white p-3 pr-2 shadow-lg ring-1 ring-black/5 ${border}`}
    >
      <ToastIcon type={toast.type} />
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-sm font-medium leading-snug text-slate-900">
          {toast.message}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
        aria-label={t("common.dismissNotification")}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden
        >
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </button>
    </li>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const { t } = useTranslation();

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const dismissAll = useCallback(() => {
    setToasts([]);
  }, []);

  const push = useCallback(
    (
      record: Omit<ToastRecord, "id" | "duration"> & {
        id?: string;
        duration?: number | null;
      }
    ) => {
      const id = record.id ?? newToastId();
      const duration = resolveDuration(record.type, record.duration);

      const next: ToastRecord = {
        id,
        type: record.type,
        message: record.message,
        duration,
      };

      setToasts((prev) => {
        const merged = [...prev, next];
        return merged.length > MAX_TOASTS ? merged.slice(-MAX_TOASTS) : merged;
      });
      return id;
    },
    []
  );

  const success = useCallback(
    (message: string, options?: ToastOptions) =>
      push({
        type: "success",
        message,
        id: options?.id,
        duration: options?.duration,
      }),
    [push]
  );

  const error = useCallback(
    (message: string, options?: ToastOptions) =>
      push({
        type: "error",
        message,
        id: options?.id,
        duration: options?.duration,
      }),
    [push]
  );

  const loading = useCallback(
    (message: string, options?: Pick<ToastOptions, "id">) =>
      push({
        type: "loading",
        message,
        id: options?.id,
        duration: null,
      }),
    [push]
  );

  const value = useMemo(
    () => ({
      toasts,
      success,
      error,
      loading,
      dismiss,
      dismissAll,
    }),
    [toasts, success, error, loading, dismiss, dismissAll]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[100] flex flex-col items-stretch gap-2 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:items-end"
      >
        <ol
          className="flex list-none flex-col gap-2 p-0"
          aria-label={t("common.notifications")}
          aria-live="polite"
          aria-relevant="additions text"
        >
          {toasts.map((toast) => (
            <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
          ))}
        </ol>
      </div>
    </ToastContext.Provider>
  );
}
