const TOKEN_KEY = "invoicing_auth_token";
const API_BASE_KEY = "invoicing_api_base_url";
const ORG_ID_KEY = "invoicing_organization_id";
const ORG_NAME_KEY = "invoicing_organization_name";
const ORG_CURRENCY_KEY = "invoicing_organization_currency";
const ORG_LANGUAGE_KEY = "invoicing_organization_language";
const USER_EMAIL_KEY = "invoicing_user_email";
// Exported so other tabs/windows of the same origin can react to a change
// via the native `storage` event (see EMAIL_VERIFIED_STORAGE_KEY usage in
// AppShell/verify-email) — this is what lets the "email not verified"
// banner disappear in an already-open tab the moment verification succeeds
// in a *different* tab, with no navigation or manual refresh needed there.
export const EMAIL_VERIFIED_STORAGE_KEY = "invoicing_email_verified";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAuthSession(params: {
  token: string;
  apiBaseUrl: string;
  organizationId: string;
  organizationName?: string;
  organizationCurrency?: string;
  organizationLanguage?: string;
  userEmail?: string;
  emailVerified?: boolean;
}): void {
  window.localStorage.setItem(TOKEN_KEY, params.token.trim());
  window.localStorage.setItem(API_BASE_KEY, params.apiBaseUrl.trim().replace(/\/$/, ""));
  window.localStorage.setItem(ORG_ID_KEY, params.organizationId.trim());
  if (params.organizationName) {
    window.localStorage.setItem(ORG_NAME_KEY, params.organizationName);
  }
  if (params.organizationCurrency) {
    window.localStorage.setItem(ORG_CURRENCY_KEY, params.organizationCurrency);
  }
  if (params.organizationLanguage) {
    window.localStorage.setItem(ORG_LANGUAGE_KEY, params.organizationLanguage);
  }
  if (params.userEmail) {
    window.localStorage.setItem(USER_EMAIL_KEY, params.userEmail);
  }
  if (params.emailVerified !== undefined) {
    window.localStorage.setItem(EMAIL_VERIFIED_STORAGE_KEY, String(params.emailVerified));
  }
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(API_BASE_KEY);
  window.localStorage.removeItem(ORG_ID_KEY);
  window.localStorage.removeItem(ORG_NAME_KEY);
  window.localStorage.removeItem(ORG_CURRENCY_KEY);
  window.localStorage.removeItem(ORG_LANGUAGE_KEY);
  window.localStorage.removeItem(USER_EMAIL_KEY);
  window.localStorage.removeItem(EMAIL_VERIFIED_STORAGE_KEY);
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

export function updateOrganizationName(name: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ORG_NAME_KEY, name);
}

export function getOrganizationCurrency(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ORG_CURRENCY_KEY);
}

export function updateOrganizationCurrency(currencyCode: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ORG_CURRENCY_KEY, currencyCode);
}

export function getOrganizationLanguage(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ORG_LANGUAGE_KEY);
}

export function updateOrganizationLanguage(language: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ORG_LANGUAGE_KEY, language);
}

export function getUserEmail(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(USER_EMAIL_KEY);
}

export function getEmailVerified(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(EMAIL_VERIFIED_STORAGE_KEY) === "true";
}

/** Writes the latest known verification state, whenever it's freshly
 * learned from the server (GET /auth/me or POST /auth/verify-email) —
 * never guessed or assumed locally. Writing to localStorage (rather than
 * only React state) is what makes the "banner disappears with no
 * navigation or refresh" behavior work across tabs: the browser fires a
 * `storage` event in every *other* tab of the same origin when this key
 * changes, which AppShell listens for. */
export function setEmailVerified(verified: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(EMAIL_VERIFIED_STORAGE_KEY, String(verified));
}

export function isAuthenticated(): boolean {
  return Boolean(getAuthToken() && getApiBaseUrl() && getOrganizationId());
}
