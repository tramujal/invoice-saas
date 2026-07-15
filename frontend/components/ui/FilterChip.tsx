type FilterChipProps = {
  label: string;
  onRemove: () => void;
  removeLabel: string;
};

/** A removable pill summarizing one active filter, e.g. "Status: Paid ×".
 * Translation-agnostic like the other ui/ primitives -- callers pass
 * already-translated text. */
export function FilterChip({ label, onRemove, removeLabel }: FilterChipProps) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 py-1 pl-3 pr-1.5 text-xs font-medium text-slate-700">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={removeLabel}
        className="rounded-full p-0.5 text-slate-500 outline-none transition hover:bg-slate-200 hover:text-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-slate-400"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden>
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </button>
    </span>
  );
}
