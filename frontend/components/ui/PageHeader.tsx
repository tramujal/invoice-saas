import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  actions?: ReactNode;
};

export function PageHeader({ title, subtitle, icon, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            {icon}
          </span>
        ) : null}
        {/* min-w-0 lets this title block shrink below its own content's
            natural width -- needed because `title` is sometimes an
            unbroken string with no natural wrap point (e.g. a user's
            email address on the platform-admin user detail page), which
            would otherwise force this flex item (and the page) wider
            than the viewport on mobile. break-words/[overflow-wrap:anywhere]
            on the heading itself is what actually lets it wrap once it
            can shrink. */}
        <div className="min-w-0">
          <h1 className="break-words text-2xl font-semibold tracking-tight text-slate-900 [overflow-wrap:anywhere]">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-1 break-words text-sm text-slate-500 [overflow-wrap:anywhere]">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}
