const TOKEN_KEY = "invoicing_auth_token";
const API_BASE_KEY = "invoicing_api_base_url";
const ORG_ID_KEY = "invoicing_organization_id";
const ORG_NAME_KEY = "invoicing_organization_name";
const USER_EMAIL_KEY = "invoicing_user_email";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAuthSession(params: {
  token: string;
  apiBaseUrl: string;
  organizationId: string;
  organizationName?: string;
  userEmail?: string;
}): void {
  window.localStorage.setItem(TOKEN_KEY, params.token.trim());
  window.localStorage.setItem(API_BASE_KEY, params.apiBaseUrl.trim().replace(/\/$/, ""));
  window.localStorage.setItem(ORG_ID_KEY, params.organizationId.trim());
  if (params.organizationName) {
    window.localStorage.setItem(ORG_NAME_KEY, params.organizationName);
  }
  if (params.userEmail) {
    window.localStorage.setItem(USER_EMAIL_KEY, params.userEmail);
  }
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(API_BASE_KEY);
  window.localStorage.removeItem(ORG_ID_KEY);
  window.localStorage.removeItem(ORG_NAME_KEY);
  window.localStorage.removeItem(USER_EMAIL_KEY);
}

export function getApiBaseUrl(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(API_BASE_KEY);
}

export function getOrganizationId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ORG_ID_KEY);
}

export function getOrganizationName(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ORG_NAME_KEY);
}

export function getUserEmail(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(USER_EMAIL_KEY);
}

export function isAuthenticated(): boolean {
  return Boolean(getAuthToken() && getApiBaseUrl() && getOrganizationId());
}
