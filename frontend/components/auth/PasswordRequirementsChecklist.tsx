"use client";

import {
  checkPasswordRequirements,
  PASSWORD_REQUIREMENT_KEYS,
  type PasswordRequirementKey,
} from "@/lib/password-policy";
import type { TranslateFn } from "@/lib/i18n/useTranslation";

const LABEL_KEY: Record<PasswordRequirementKey, string> = {
  minLength: "auth.passwordRequirementMinLength",
  uppercase: "auth.passwordRequirementUppercase",
  lowercase: "auth.passwordRequirementLowercase",
  number: "auth.passwordRequirementNumber",
};

/** Live pass/fail checklist for the password policy, shared by the
 * register form and the reset-password form so the rules are only ever
 * rendered in one place. */
export function PasswordRequirementsChecklist({
  password,
  t,
}: {
  password: string;
  t: TranslateFn;
}) {
  const status = checkPasswordRequirements(password);

  return (
    <ul className="mt-2 space-y-1 text-xs">
      {PASSWORD_REQUIREMENT_KEYS.map((key) => {
        const met = status[key];
        return (
          <li
            key={key}
            className={`flex items-center gap-1.5 ${met ? "text-emerald-700" : "text-slate-500"}`}
          >
            <span aria-hidden>{met ? "✓" : "○"}</span>
            {t(LABEL_KEY[key])}
          </li>
        );
      })}
    </ul>
  );
}
