import type { ReactNode } from "react";

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ icon, title, description, action, className = "" }: EmptyStateProps) {
  return (
    <div
      className={`rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-6 py-12 text-center sm:px-10 ${className}`}
    >
      {icon ? (
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-200/80 text-slate-600">
          {icon}
        </div>
      ) : null}
      <h2 className={`text-lg font-semibold text-slate-900 ${icon ? "mt-4" : ""}`}>{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
