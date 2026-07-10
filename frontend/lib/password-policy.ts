/** Mirrors the backend policy (app/security.py: password_meets_policy) so
 * register and reset-password forms reject the same passwords the server
 * would, before ever submitting. Intentionally no special-character rule. */

export const PASSWORD_MIN_LENGTH = 8;

export type PasswordRequirementKey = "minLength" | "uppercase" | "lowercase" | "number";

export type PasswordRequirementStatus = Record<PasswordRequirementKey, boolean>;

export const PASSWORD_REQUIREMENT_KEYS: PasswordRequirementKey[] = [
  "minLength",
  "uppercase",
  "lowercase",
  "number",
];

export function checkPasswordRequirements(password: string): PasswordRequirementStatus {
  return {
    minLength: password.length >= PASSWORD_MIN_LENGTH,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    number: /[0-9]/.test(password),
  };
}

export function isPasswordValid(password: string): boolean {
  const status = checkPasswordRequirements(password);
  return PASSWORD_REQUIREMENT_KEYS.every((key) => status[key]);
}
