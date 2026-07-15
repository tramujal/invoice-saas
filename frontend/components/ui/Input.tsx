import { forwardRef } from "react";
import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  ReactNode,
} from "react";

/** Shared input/select field styling -- converges the app's ~60/40
 * px-3 py-2 / px-3 py-2.5 split onto one value, and standardizes on
 * focus-visible: like Button.tsx. Color/radius/ring language was already
 * consistent app-wide (rounded-lg, slate-200 border, slate-400 ring). */

const FIELD_BASE_CLASS =
  "rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-900 outline-none transition focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:bg-slate-50";

// fullWidth is a boolean prop (not baked into the base string) rather than
// relying on a caller's className to "override" w-full -- Tailwind classes
// all share equal CSS specificity, so whichever of w-full/w-28/etc. happens
// to come later in the compiled stylesheet wins, not whichever comes later
// in the className string. Keeping width fully out of the base class avoids
// that footgun entirely.
export function fieldClassName(className?: string, fullWidth: boolean = true): string {
  return [FIELD_BASE_CLASS, fullWidth ? "w-full" : null, className].filter(Boolean).join(" ");
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & { fullWidth?: boolean };

// forwardRef so callers that need to focus/select the underlying field (e.g.
// a modal auto-focusing its first field on open) can still attach a ref, the
// same as they could with a raw <input>.
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, fullWidth = true, ...rest },
  ref
) {
  return <input ref={ref} className={fieldClassName(className, fullWidth)} {...rest} />;
});

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  children: ReactNode;
  fullWidth?: boolean;
};

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, fullWidth = true, children, ...rest },
  ref
) {
  return (
    <select ref={ref} className={fieldClassName(className, fullWidth)} {...rest}>
      {children}
    </select>
  );
});

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { fullWidth?: boolean };

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, fullWidth = true, ...rest },
  ref
) {
  return <textarea ref={ref} className={fieldClassName(className, fullWidth)} {...rest} />;
});
