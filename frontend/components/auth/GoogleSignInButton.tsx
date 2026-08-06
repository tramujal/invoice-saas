"use client";

/** "Continue with Google" -- a full-page navigation into the backend's
 * GET /auth/google/start (never a fetch/XHR: this must be a real browser
 * navigation so Google's own redirect chain and the httpOnly CSRF-state
 * cookie work correctly). Rendered only when the caller already knows
 * Google Sign-In is configured (see GET /auth/google/config, checked by
 * the login page before this component is shown at all). */
type GoogleSignInButtonProps = {
  apiBaseUrl: string;
  label: string;
  disabled?: boolean;
};

export function GoogleSignInButton({ apiBaseUrl, label, disabled = false }: GoogleSignInButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        window.location.href = `${apiBaseUrl.replace(/\/$/, "")}/auth/google/start`;
      }}
      className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden focusable="false">
        <path
          fill="#FFC107"
          d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.6-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.7 6 29.7 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.4-.4-3.5z"
        />
        <path
          fill="#FF3D00"
          d="M6.3 14.7l6.6 4.8C14.6 15.9 18.9 13 24 13c3.1 0 5.8 1.1 8 3l5.7-5.7C34.7 6 29.7 4 24 4c-7.4 0-13.8 4.2-17 10.3-.3.4-.5.9-.7 1.4z"
        />
        <path
          fill="#4CAF50"
          d="M24 44c5.6 0 10.5-1.9 14-5.2l-6.5-5.5c-2 1.4-4.6 2.3-7.5 2.3-5.3 0-9.7-3.4-11.3-8.1l-6.6 5.1C9.9 39.6 16.4 44 24 44z"
        />
        <path
          fill="#1976D2"
          d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.2-4.1 5.6l6.5 5.5c-.5.4 6.9-5 6.9-15.6 0-1.2-.1-2.4-.4-3.5z"
        />
      </svg>
      {label}
    </button>
  );
}
