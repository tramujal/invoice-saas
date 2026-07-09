const TOKEN_KEY = "invoicing_auth_token";
const API_BASE_KEY = "invoicing_api_base_url";
const ORG_ID_KEY = "invoicing_organization_id";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAuthSession(params: {
  token: string;
  apiBaseUrl: string;
  organizationId: string;
}): void {
  window.localStorage.setItem(TOKEN_KEY, params.token.trim());
  window.localStorage.setItem(API_BASE_KEY, params.apiBaseUrl.trim().replace(/\/$/, ""));
  window.localStorage.setItem(ORG_ID_KEY, params.organizationId.trim());
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(API_BASE_KEY);
  window.localStorage.removeItem(ORG_ID_KEY);
}

export function getApiBaseUrl(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(API_BASE_KEY);
}

export function getOrganizationId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ORG_ID_KEY);
}

export function isAuthenticated(): boolean {
  return Boolean(getAuthToken() && getApiBaseUrl() && getOrganizationId());
}
