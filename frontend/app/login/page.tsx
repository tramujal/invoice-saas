"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { isAuthenticated, setAuthSession } from "@/lib/auth-storage";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export default function LoginPage() {
  const router = useRouter();
  const [apiBaseUrl, setApiBaseUrl] = useState(defaultApi);
  const [token, setToken] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthenticated()) router.replace("/");
  }, [router]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!apiBaseUrl.trim() || !token.trim() || !organizationId.trim()) {
      setError("Please fill in all fields.");
      return;
    }
    setAuthSession({
      apiBaseUrl: apiBaseUrl.trim(),
      token: token.trim(),
      organizationId: organizationId.trim(),
    });
    router.replace("/");
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">
          Sign in
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Connect to your FastAPI backend. The token is sent as{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">
            Authorization: Bearer …
          </code>
          .
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="api"
            >
              API base URL
            </label>
            <input
              id="api"
              type="url"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000"
            />
          </div>
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="token"
            >
              Auth token
            </label>
            <input
              id="token"
              type="password"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="User id from seed / JWT"
            />
          </div>
          <div>
            <label
              className="block text-xs font-medium text-slate-700"
              htmlFor="org"
            >
              Organization ID
            </label>
            <input
              id="org"
              type="text"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
              value={organizationId}
              onChange={(e) => setOrganizationId(e.target.value)}
              placeholder="UUID"
            />
          </div>

          {error ? (
            <p className="text-sm text-red-600" role="alert">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
