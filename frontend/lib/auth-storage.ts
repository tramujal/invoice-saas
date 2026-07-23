const TOKEN_KEY = "invoicing_auth_token";
const API_BASE_KEY = "invoicing_api_base_url";
const ORG_ID_KEY = "invoicing_organization_id";
const ORG_NAME_KEY = "invoicing_organization_name";
const ORG_CURRENCY_KEY = "invoicing_organization_currency";
const ORG_LANGUAGE_KEY = "invoicing_organization_language";
const ORG_PERMISSIONS_KEY = "invoicing_organization_permissions";
const USER_EMAIL_KEY = "invoicing_user_email";
// Deliberately separate from ORG_PERMISSIONS_KEY -- a platform role is not
// scoped to any organization (see app.platform_permissions on the
// backend), so it must never be cleared or overwritten by an organization
// switch the way ORG_PERMISSIONS_KEY is.
const PLATFORM_ROLE_KEY = "invoicing_platform_role";
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
  // Optional -- a platform-admin-only account (zero organization
  // memberships, see isPlatformAdminAuthenticated) has no organization to
  // set. Ordinary login/register always pass this, since every
  // registration creates exactly one organization.
  organizationId?: string;
  organizationName?: string;
  organizationCurrency?: string;
  organizationLanguage?: string;
  organizationPermissions?: string[];
  userEmail?: string;
  emailVerified?: boolean;
  platformRole?: string | null;
}): void {
  window.localStorage.setItem(TOKEN_KEY, params.token.trim());
  window.localStorage.setItem(API_BASE_KEY, params.apiBaseUrl.trim().replace(/\/$/, ""));
  if (params.organizationId) {
    window.localStorage.setItem(ORG_ID_KEY, params.organizationId.trim());
  }
  if (params.organizationName) {
    window.localStorage.setItem(ORG_NAME_KEY, params.organizationName);
  }
  if (params.organizationCurrency) {
    window.localStorage.setItem(ORG_CURRENCY_KEY, params.organizationCurrency);
  }
  if (params.organizationLanguage) {
    window.localStorage.setItem(ORG_LANGUAGE_KEY, params.organizationLanguage);
  }
  if (params.organizationPermissions) {
    window.localStorage.setItem(ORG_PERMISSIONS_KEY, JSON.stringify(params.organizationPermissions));
  }
  if (params.userEmail) {
    window.localStorage.setItem(USER_EMAIL_KEY, params.userEmail);
  }
  if (params.emailVerified !== undefined) {
    window.localStorage.setItem(EMAIL_VERIFIED_STORAGE_KEY, String(params.emailVerified));
  }
  if (params.platformRole !== undefined) {
    if (params.platformRole) {
      window.localStorage.setItem(PLATFORM_ROLE_KEY, params.platformRole);
    } else {
      window.localStorage.removeItem(PLATFORM_ROLE_KEY);
    }
  }
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(API_BASE_KEY);
  window.localStorage.removeItem(ORG_ID_KEY);
  window.localStorage.removeItem(ORG_NAME_KEY);
  window.localStorage.removeItem(ORG_CURRENCY_KEY);
  window.localStorage.removeItem(ORG_LANGUAGE_KEY);
  window.localStorage.removeItem(ORG_PERMISSIONS_KEY);
  window.localStorage.removeItem(USER_EMAIL_KEY);
  window.localStorage.removeItem(EMAIL_VERIFIED_STORAGE_KEY);
  window.localStorage.removeItem(PLATFORM_ROLE_KEY);
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

/** The caller's own effective permission set in the active organization --
 * see app.permissions.Permission (backend) / lib/permissions.ts (frontend).
 * Refreshed on every GET /auth/me (AppShell) and organization switch, never
 * derived from a cached role name. Returns [] (not null) when absent so
 * callers can pass the result straight to hasPermission() without a guard. */
export function getOrganizationPermissions(): string[] {
  if (typeof window === "undefined") return [];
  const raw = window.localStorage.getItem(ORG_PERMISSIONS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function updateOrganizationPermissions(permissions: string[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ORG_PERMISSIONS_KEY, JSON.stringify(permissions));
}

/** Switches the active organization in place (same token, same user) --
 * used by the accept-invitation flow (a newly-accepted org must become
 * reachable immediately) and the organization switcher. Unlike
 * setAuthSession, this never touches the token/apiBaseUrl/userEmail keys,
 * since those don't change when switching organizations. */
export function updateActiveOrganization(params: {
  organizationId: string;
  organizationName?: string;
  organizationCurrency?: string;
  organizationLanguage?: string;
  organizationPermissions?: string[];
}): void {
  if (typeof window === "undefined") return;
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
  if (params.organizationPermissions) {
    window.localStorage.setItem(ORG_PERMISSIONS_KEY, JSON.stringify(params.organizationPermissions));
  }
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

/** A user's own platform-administration role, or null -- see
 * app.platform_permissions on the backend. Refreshed from GET /auth/me by
 * both AppShell (to decide whether to show the Platform Admin entry
 * link) and PlatformAdminShell (to re-verify on every load, since a role
 * can be revoked mid-session). */
export function getPlatformRole(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(PLATFORM_ROLE_KEY);
}

/** Writes the latest known platform role, including clearing it (pass
 * null) when a previously-granted role has been revoked -- never merely
 * skipped, so a stale cached role can't outlive the server's own record
 * of it for longer than the next /auth/me refresh. */
export function updatePlatformRole(role: string | null): void {
  if (typeof window === "undefined") return;
  if (role) {
    window.localStorage.setItem(PLATFORM_ROLE_KEY, role);
  } else {
    window.localStorage.removeItem(PLATFORM_ROLE_KEY);
  }
}

/** The platform-admin equivalent of isAuthenticated() -- deliberately
 * does NOT require an organization id, since a platform operator may
 * have zero organization memberships. */
export function isPlatformAdminAuthenticated(): boolean {
  return Boolean(getAuthToken() && getApiBaseUrl() && getPlatformRole());
}
