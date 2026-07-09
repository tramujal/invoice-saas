import {
  clearAuthSession,
  getApiBaseUrl,
  getAuthToken,
  getOrganizationId,
} from "@/lib/auth-storage";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

function buildUrl(path: string): string {
  const base = getApiBaseUrl();
  if (!base) throw new ApiError("API base URL is not configured", 0);
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}

/**
 * Minimal fetch wrapper: attaches Bearer token, JSON headers, and maps errors.
 */
export async function apiFetch<T = Json>(
  path: string,
  init?: RequestInit & { parseJson?: boolean }
): Promise<T> {
  const { parseJson = true, headers: initHeaders, ...rest } = init ?? {};
  const headers = new Headers(initHeaders);

  const token = getAuthToken();
  if (!token) throw new ApiError("Not authenticated", 401);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "application/json");
  if (rest.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(buildUrl(path), { ...rest, headers });

  if (res.status === 401) {
    clearAuthSession();
  }

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(`Request failed (${res.status})`, res.status, body);
  }

  if (res.status === 204 || !parseJson) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

/**
 * Like apiFetch, but resolves to a Blob for binary responses (e.g. PDFs)
 * instead of parsing JSON.
 */
export async function apiFetchBlob(
  path: string,
  init?: RequestInit
): Promise<Blob> {
  const headers = new Headers(init?.headers);

  const token = getAuthToken();
  if (!token) throw new ApiError("Not authenticated", 401);
  headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(buildUrl(path), { ...init, headers });

  if (res.status === 401) {
    clearAuthSession();
  }

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(`Request failed (${res.status})`, res.status, body);
  }

  return res.blob();
}

/**
 * Unauthenticated POST request used by the login/register flows, before a
 * token exists. Reuses the same ApiError shape as apiFetch so callers can
 * share error-formatting logic.
 */
export async function authRequest<T>(
  apiBaseUrl: string,
  path: string,
  body: unknown
): Promise<T> {
  const base = apiBaseUrl.trim().replace(/\/$/, "");
  if (!base) throw new ApiError("API base URL is not configured", 0);
  const normalized = path.startsWith("/") ? path : `/${path}`;

  const res = await fetch(`${base}${normalized}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    let responseBody: unknown;
    try {
      responseBody = await res.json();
    } catch {
      responseBody = await res.text();
    }
    throw new ApiError(`Request failed (${res.status})`, res.status, responseBody);
  }

  return (await res.json()) as T;
}

export function orgPath(segment: string): string {
  const orgId = getOrganizationId();
  if (!orgId) throw new ApiError("Organization is not configured", 0);
  const s = segment.startsWith("/") ? segment.slice(1) : segment;
  return `/organizations/${orgId}/${s}`;
}
